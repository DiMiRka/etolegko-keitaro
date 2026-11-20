import re
import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.errors import AppError
from app.keitaro import KeitaroClient, KeitaroError
from app.models import Campaign
from app.offers import OfferCatalog
from app.streams import fetch_streams, load_campaign

GEO_RE = re.compile(r"^[A-Z]{2}$")


def full_name(name: str, prefix: str) -> str:
    name = name.strip()
    if not name:
        raise AppError("Укажите название кампании")
    return name if name.startswith(prefix) else prefix + name


def normalize_geo(geo: str) -> str:
    geo = geo.strip().upper()
    if not GEO_RE.match(geo):
        raise AppError("Гео: двухбуквенный код страны, например AU")
    return geo


def make_alias(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return f"{slug}-{secrets.token_hex(3)}"


def campaign_payload(name: str, alias: str, settings: Settings) -> dict:
    return {
        "name": name,
        "alias": alias,
        "type": "position",
        "state": "active",
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_currency": "USD",
        "cost_auto": True,
        "domain_id": settings.keitaro_domain_id,
        "group_id": settings.keitaro_group_id,
        "traffic_source_id": settings.keitaro_traffic_source_id,
    }


def geo_stream_payload(campaign_id: int, geo: str, redirect_url: str) -> dict:
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": geo_stream_name(geo),
        "position": 1,
        "state": "active",
        "schema": "redirect",
        "action_type": "http",
        "action_payload": redirect_url,
        "collect_clicks": True,
        "filters": [{"name": "country", "mode": "accept", "payload": [geo]}],
    }


def offer_stream_payload(campaign_id: int, offer_id: int) -> dict:
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": "Offers",
        "position": 2,
        "state": "active",
        "schema": "landings",
        "action_type": "http",
        "collect_clicks": True,
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
    }


async def create_campaign(
    session: AsyncSession,
    kt: KeitaroClient,
    catalog: OfferCatalog,
    settings: Settings,
    name: str,
    geo: str,
    offer_id: int,
) -> Campaign:
    name = full_name(name, settings.campaign_prefix)
    geo = normalize_geo(geo)
    if await catalog.get(offer_id) is None:
        raise AppError(f"Оффер {offer_id} не найден в Keitaro")

    created = await kt.create_campaign(campaign_payload(name, make_alias(name), settings))
    campaign_id = created["id"]
    try:
        await kt.create_stream(geo_stream_payload(campaign_id, geo, settings.geo_redirect_url))
        await kt.create_stream(offer_stream_payload(campaign_id, offer_id))
    except KeitaroError as e:
        try:
            await kt.delete_campaign(campaign_id)
        except KeitaroError:
            raise AppError(f"Не удалось создать потоки ({e}), кампания {campaign_id} осталась в Keitaro") from e
        raise AppError(f"Не удалось создать потоки, кампания удалена: {e}") from e

    campaign = Campaign(keitaro_id=campaign_id, name=created["name"], alias=created["alias"], geo=geo)
    session.add(campaign)
    await session.commit()
    campaign = await load_campaign(session, campaign.id)
    return await fetch_streams(session, kt, campaign)


def country_filter(stream: dict) -> dict | None:
    return next((f for f in stream.get("filters") or [] if f.get("name") == "country"), None)


def geo_stream_name(geo: str) -> str:
    return f"{geo} -> Google"


async def update_campaign(
    session: AsyncSession,
    kt: KeitaroClient,
    settings: Settings,
    campaign: Campaign,
    name: str | None = None,
    geo: str | None = None,
) -> Campaign:
    new_name = full_name(name, settings.campaign_prefix) if name is not None else None
    new_geo = normalize_geo(geo) if geo is not None else None

    geo_stream = None
    if new_geo is not None and new_geo != campaign.geo:
        kt_streams = sorted(await kt.list_streams(campaign.keitaro_id), key=lambda s: s.get("position") or 0)
        geo_stream = next((s for s in kt_streams if country_filter(s)), None)
        if geo_stream is None:
            raise AppError("В кампании нет потока с фильтром по стране, гео поменять нельзя")

    if new_name is not None and new_name != campaign.name:
        await kt.update_campaign(campaign.keitaro_id, {"name": new_name})

    if geo_stream is not None:
        filters = []
        for f in geo_stream["filters"]:
            item = {"id": f["id"], "name": f["name"], "mode": f["mode"], "payload": f["payload"]}
            if f is country_filter(geo_stream):
                item["payload"] = [new_geo]
            filters.append(item)
        payload: dict = {"filters": filters}
        old = (country_filter(geo_stream)["payload"] or [""])[0]
        if geo_stream["name"] == geo_stream_name(old):
            payload["name"] = geo_stream_name(new_geo)
        await kt.update_stream(geo_stream["id"], payload)

    return await fetch_streams(session, kt, campaign)
