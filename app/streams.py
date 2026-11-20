from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.errors import AppError as StreamError
from app.errors import NotFound
from app.keitaro import KeitaroClient, KeitaroError
from app.models import Campaign, OfferState, Stream, StreamOffer
from app.weights import WeightError, rebalance


async def load_campaign(session: AsyncSession, campaign_id: int) -> Campaign:
    campaign = await session.scalar(
        select(Campaign)
        .where(Campaign.id == campaign_id)
        .options(selectinload(Campaign.streams).selectinload(Stream.offers))
    )
    if campaign is None:
        raise NotFound(f"Кампания {campaign_id} не найдена")
    return campaign


async def load_stream(session: AsyncSession, stream_id: int) -> Stream:
    stream = await session.scalar(
        select(Stream).where(Stream.id == stream_id).options(selectinload(Stream.offers))
    )
    if stream is None:
        raise NotFound(f"Поток {stream_id} не найден")
    return stream


def find_offer(stream: Stream, offer_id: int) -> StreamOffer:
    for o in stream.offers:
        if o.offer_id == offer_id:
            return o
    raise NotFound(f"Оффера {offer_id} нет в потоке")


async def import_campaign(session: AsyncSession, kt: KeitaroClient, keitaro_id: int) -> Campaign:
    existing = await session.scalar(select(Campaign).where(Campaign.keitaro_id == keitaro_id))
    if existing is not None:
        return await load_campaign(session, existing.id)
    try:
        data = await kt.get_campaign(keitaro_id)
    except KeitaroError as e:
        if e.status == 404:
            raise NotFound(f"Кампании {keitaro_id} нет в Keitaro") from e
        raise
    campaign = Campaign(keitaro_id=data["id"], name=data["name"], alias=data["alias"])
    session.add(campaign)
    await session.commit()
    return await load_campaign(session, campaign.id)


async def forget_campaign(session: AsyncSession, campaign: Campaign) -> None:
    await session.delete(campaign)
    await session.commit()


async def _offer_names(kt: KeitaroClient) -> dict[int, str]:
    try:
        return {o["id"]: o["name"] for o in await kt.list_offers()}
    except KeitaroError:
        return {}


def _sync_offers(stream: Stream, kt_offers: list[dict], names: dict[int, str]) -> None:
    remote = {o["offer_id"]: o for o in kt_offers}
    for local in list(stream.offers):
        if local.offer_id in remote:
            data = remote.pop(local.offer_id)
            local.share = local.published_share = int(data["share"])
            local.state = local.published_state = OfferState.active
            local.disabled = data.get("state") == "disabled"
        elif local.published_state is None:
            stream.offers.remove(local)
        else:
            local.share = local.published_share = 0
            local.state = local.published_state = OfferState.removed
            local.pinned = local.disabled = False
        if local.offer_id in names:
            local.offer_name = names[local.offer_id]
    for offer_id, data in remote.items():
        share = int(data["share"])
        stream.offers.append(StreamOffer(
            offer_id=offer_id,
            offer_name=names.get(offer_id, ""),
            share=share,
            published_share=share,
            state=OfferState.active,
            published_state=OfferState.active,
            pinned=False,
            disabled=data.get("state") == "disabled",
        ))


def _geo_of(kt_streams: list[dict]) -> str | None:
    for s in sorted(kt_streams, key=lambda s: s.get("position") or 0):
        for f in s.get("filters") or []:
            if f.get("name") == "country" and f.get("mode") == "accept" and len(f.get("payload") or []) == 1:
                return f["payload"][0]
    return None


async def fetch_streams(session: AsyncSession, kt: KeitaroClient, campaign: Campaign) -> Campaign:
    try:
        info = await kt.get_campaign(campaign.keitaro_id)
        kt_streams = await kt.list_streams(campaign.keitaro_id)
    except KeitaroError as e:
        if e.status == 404:
            raise StreamError(
                f"Кампании {campaign.keitaro_id} больше нет в Keitaro (удалена или в архиве). "
                "Её можно убрать из списка"
            ) from e
        raise
    campaign.name, campaign.alias = info["name"], info["alias"]
    campaign.domain_id = info.get("domain_id")
    campaign.group_id = info.get("group_id")
    campaign.traffic_source_id = info.get("traffic_source_id")
    campaign.geo = _geo_of(kt_streams) or campaign.geo
    names = await _offer_names(kt)
    now = datetime.now(UTC).replace(tzinfo=None)
    local = {s.keitaro_id: s for s in campaign.streams}
    seen = set()

    for data in kt_streams:
        seen.add(data["id"])
        stream = local.get(data["id"])
        if stream is None:
            stream = Stream(keitaro_id=data["id"], name=data["name"], offers=[])
            campaign.streams.append(stream)
        stream.name = data["name"]
        stream.position = data.get("position") or 0
        stream.fetched_at = now
        stream.last_error = None
        kt_offers = data.get("offers") or []
        stream.has_offers = data.get("schema") == "landings" or bool(kt_offers) or bool(stream.offers)
        if stream.has_offers:
            _sync_offers(stream, kt_offers, names)

    for keitaro_id, stream in local.items():
        if keitaro_id not in seen:
            campaign.streams.remove(stream)

    await session.commit()
    return await load_campaign(session, campaign.id)


def _rebalance(stream: Stream) -> None:
    try:
        rebalance([o for o in stream.offers if not o.disabled])
    except WeightError as e:
        raise StreamError(str(e)) from e


async def add_offer(session: AsyncSession, stream: Stream, offer_id: int, offer_name: str = "") -> StreamOffer:
    if not stream.has_offers:
        raise StreamError("В этот поток офферы не добавляются")
    for o in stream.offers:
        if o.offer_id == offer_id:
            if o.is_active:
                raise StreamError(f"Оффер {offer_id} уже в потоке")
            await bring_back(session, stream, o)
            return o
    offer = StreamOffer(
        offer_id=offer_id, offer_name=offer_name, share=0, pinned=False, disabled=False, state=OfferState.active
    )
    stream.offers.append(offer)
    try:
        _rebalance(stream)
    except StreamError:
        stream.offers.remove(offer)
        raise
    await session.commit()
    return offer


async def remove_offer(session: AsyncSession, stream: Stream, offer: StreamOffer) -> None:
    if not offer.is_active:
        raise StreamError("Оффер уже удалён")
    before = (offer.state, offer.share, offer.pinned)
    index = stream.offers.index(offer)
    if offer.published_state is None:
        stream.offers.remove(offer)
    else:
        offer.state, offer.share, offer.pinned = OfferState.removed, 0, False
    try:
        _rebalance(stream)
    except StreamError:
        if offer not in stream.offers:
            stream.offers.insert(index, offer)
        offer.state, offer.share, offer.pinned = before
        raise
    await session.commit()


async def bring_back(session: AsyncSession, stream: Stream, offer: StreamOffer) -> None:
    if offer.is_active:
        raise StreamError("Оффер и так активен")
    offer.state = OfferState.active
    try:
        _rebalance(stream)
    except StreamError:
        offer.state, offer.share = OfferState.removed, 0
        raise
    await session.commit()


async def set_pin(
    session: AsyncSession, stream: Stream, offer: StreamOffer, pinned: bool, share: int | None = None
) -> None:
    if not offer.is_active:
        raise StreamError("Удалённый оффер нельзя закрепить")
    if offer.disabled:
        raise StreamError("Оффер отключён в Keitaro, его доля не пересчитывается")
    if share is not None and not 0 <= share <= 100:
        raise StreamError("Доля должна быть от 0 до 100")
    before = (offer.pinned, [(o, o.share) for o in stream.offers])
    offer.pinned = pinned
    if pinned and share is not None:
        offer.share = share
    try:
        _rebalance(stream)
    except StreamError:
        offer.pinned = before[0]
        for o, s in before[1]:
            o.share = s
        raise
    await session.commit()


async def cancel(session: AsyncSession, stream: Stream) -> None:
    for o in list(stream.offers):
        if o.published_state is None:
            stream.offers.remove(o)
        else:
            o.share, o.state = o.published_share, o.published_state
            if not o.is_active:
                o.pinned = False
    stream.last_error = None
    await session.commit()


def push_payload(stream: Stream) -> dict:
    return {
        "offers": [
            {"offer_id": o.offer_id, "share": o.share, "state": "disabled" if o.disabled else "active"}
            for o in stream.offers
            if o.is_active
        ]
    }


async def push(session: AsyncSession, kt: KeitaroClient, stream: Stream) -> None:
    if not stream.has_offers:
        raise StreamError("В потоке нет офферов для публикации")
    active = [o for o in stream.offers if o.is_active and not o.disabled]
    if not active:
        raise StreamError("Нельзя опубликовать поток без активных офферов")
    if sum(o.share for o in active) != 100:
        raise StreamError("Сумма долей не равна 100%")
    try:
        await kt.update_stream(stream.keitaro_id, push_payload(stream))
    except KeitaroError as e:
        stream.last_error = str(e)
        await session.commit()
        raise StreamError(str(e)) from e
    for o in stream.offers:
        o.published_share, o.published_state = o.share, o.state
    stream.last_error = None
    await session.commit()
