from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app import campaigns, stats
from app import streams as svc
from app.campaigns import Tracking
from app.deps import CatalogDep, KeitaroDep, ReferencesDep, SessionDep, SettingsDep
from app.errors import AppError, NotFound
from app.keitaro import KeitaroError
from app.models import Campaign
from app.offers import offer_usage
from app.schemas import (
    CampaignCreate,
    CampaignImport,
    CampaignOut,
    CampaignShort,
    CampaignState,
    CampaignUpdate,
    OfferAdd,
    OfferOut,
    PinIn,
    StreamOut,
)

router = APIRouter(prefix="/api")


@router.get("/offers", response_model=list[OfferOut])
async def search_offers(catalog: CatalogDep, q: str = ""):
    return await catalog.search(q)


@router.get("/campaigns", response_model=list[CampaignShort])
async def list_campaigns(session: SessionDep):
    rows = await session.scalars(select(Campaign).order_by(Campaign.id.desc()))
    return [CampaignShort.of(c) for c in rows]


@router.get("/campaigns/stats")
async def campaigns_stats(
    session: SessionDep, kt: KeitaroDep, settings: SettingsDep,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
):
    ids = list(await session.scalars(select(Campaign.keitaro_id)))
    return {
        "days": days,
        "campaigns": await stats.campaigns_totals(kt, ids, days, settings.keitaro_timezone),
    }


@router.get("/offers/catalog")
async def offers_catalog(session: SessionDep, kt: KeitaroDep, catalog: CatalogDep, settings: SettingsDep):
    offers = await catalog.all()
    try:
        clicks = await stats.clicks_by_offer(kt, 7, settings.keitaro_timezone)
    except KeitaroError:
        clicks = None
    usage: dict[int, set[int]] = {}
    for row in await offer_usage(session):
        if row["state"] == "active":
            usage.setdefault(row["offer_id"], set()).add(row["campaign_id"])
    return [
        {**o, "clicks_7d": None if clicks is None else clicks.get(o["id"], 0),
         "campaigns_count": len(usage.get(o["id"], ()))}
        for o in offers
    ]


@router.get("/offers/{offer_id}")
async def offer_detail(offer_id: int, session: SessionDep, catalog: CatalogDep):
    offer = await catalog.get(offer_id)
    if offer is None:
        raise NotFound(f"Оффер {offer_id} не найден в Keitaro")
    return {**offer, "usage": await offer_usage(session, offer_id)}


@router.get("/offers/{offer_id}/stats")
async def offer_stats(
    offer_id: int, kt: KeitaroDep, catalog: CatalogDep, settings: SettingsDep,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
):
    if await catalog.get(offer_id) is None:
        raise NotFound(f"Оффер {offer_id} не найден в Keitaro")
    return await stats.offer_stats(kt, offer_id, days, settings.keitaro_timezone)


@router.get("/references")
async def get_references(references: ReferencesDep, settings: SettingsDep):
    defaults = Tracking.defaults(settings)
    return {
        **await references.all(),
        "defaults": {
            "domain_id": defaults.domain_id,
            "group_id": defaults.group_id,
            "traffic_source_id": defaults.traffic_source_id,
        },
    }


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    session: SessionDep,
    kt: KeitaroDep,
    catalog: CatalogDep,
    references: ReferencesDep,
    settings: SettingsDep,
):
    defaults = Tracking.defaults(settings)
    tracking = Tracking(
        body.domain_id or defaults.domain_id,
        body.group_id or defaults.group_id,
        body.traffic_source_id or defaults.traffic_source_id,
    )
    await references.check(tracking.domain_id, tracking.group_id, tracking.traffic_source_id)
    campaign = await campaigns.create_campaign(
        session, kt, catalog, settings, body.name, body.geo, body.offer_id, tracking
    )
    return CampaignOut.of(campaign)


@router.post("/campaigns/import", response_model=CampaignOut)
async def import_campaign(body: CampaignImport, session: SessionDep, kt: KeitaroDep):
    campaign = await svc.import_campaign(session, kt, body.keitaro_id)
    return CampaignOut.of(await svc.fetch_streams(session, kt, campaign))


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: int, session: SessionDep):
    return CampaignOut.of(await svc.load_campaign(session, campaign_id))


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: int,
    body: CampaignUpdate,
    session: SessionDep,
    kt: KeitaroDep,
    references: ReferencesDep,
    settings: SettingsDep,
):
    campaign = await svc.load_campaign(session, campaign_id)
    await references.check(body.domain_id, body.group_id, body.traffic_source_id)
    updated = await campaigns.update_campaign(
        session, kt, settings, campaign, body.name, body.geo,
        body.domain_id, body.group_id, body.traffic_source_id,
    )
    return CampaignOut.of(updated)


@router.post("/campaigns/{campaign_id}/state", response_model=CampaignOut)
async def set_campaign_state(campaign_id: int, body: CampaignState, session: SessionDep, kt: KeitaroDep):
    campaign = await svc.load_campaign(session, campaign_id)
    return CampaignOut.of(await campaigns.set_state(session, kt, campaign, body.active))


@router.delete("/campaigns/{campaign_id}", status_code=204)
async def forget_campaign(campaign_id: int, session: SessionDep):
    await svc.forget_campaign(session, await svc.load_campaign(session, campaign_id))


@router.get("/campaigns/{campaign_id}/stats")
async def campaign_stats(
    campaign_id: int, session: SessionDep, kt: KeitaroDep, settings: SettingsDep,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
):
    campaign = await svc.load_campaign(session, campaign_id)
    return await stats.campaign_stats(kt, campaign.keitaro_id, days, settings.keitaro_timezone)


@router.post("/campaigns/{campaign_id}/fetch", response_model=CampaignOut)
async def fetch_streams(campaign_id: int, session: SessionDep, kt: KeitaroDep):
    campaign = await svc.load_campaign(session, campaign_id)
    return CampaignOut.of(await svc.fetch_streams(session, kt, campaign))


@router.post("/streams/{stream_id}/offers", response_model=StreamOut)
async def add_offer(stream_id: int, body: OfferAdd, session: SessionDep, catalog: CatalogDep):
    stream = await svc.load_stream(session, stream_id)
    offer = await catalog.get(body.offer_id)
    if offer is None:
        raise AppError(f"Оффер {body.offer_id} не найден в Keitaro")
    await svc.add_offer(session, stream, body.offer_id, offer["name"])
    return StreamOut.of(stream)


@router.post("/streams/{stream_id}/offers/{offer_id}/remove", response_model=StreamOut)
async def remove_offer(stream_id: int, offer_id: int, session: SessionDep):
    stream = await svc.load_stream(session, stream_id)
    await svc.remove_offer(session, stream, svc.find_offer(stream, offer_id))
    return StreamOut.of(stream)


@router.post("/streams/{stream_id}/offers/{offer_id}/bring-back", response_model=StreamOut)
async def bring_back(stream_id: int, offer_id: int, session: SessionDep):
    stream = await svc.load_stream(session, stream_id)
    await svc.bring_back(session, stream, svc.find_offer(stream, offer_id))
    return StreamOut.of(stream)


@router.post("/streams/{stream_id}/offers/{offer_id}/pin", response_model=StreamOut)
async def pin_offer(stream_id: int, offer_id: int, body: PinIn, session: SessionDep):
    stream = await svc.load_stream(session, stream_id)
    await svc.set_pin(session, stream, svc.find_offer(stream, offer_id), body.pinned, body.share)
    return StreamOut.of(stream)


@router.post("/streams/{stream_id}/cancel", response_model=StreamOut)
async def cancel(stream_id: int, session: SessionDep):
    stream = await svc.load_stream(session, stream_id)
    await svc.cancel(session, stream)
    return StreamOut.of(stream)


@router.post("/streams/{stream_id}/push", response_model=StreamOut)
async def push(stream_id: int, session: SessionDep, kt: KeitaroDep):
    stream = await svc.load_stream(session, stream_id)
    await svc.push(session, kt, stream)
    return StreamOut.of(stream)
