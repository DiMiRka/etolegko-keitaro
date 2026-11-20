from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app import campaigns, stats
from app import streams as svc
from app.campaigns import Tracking
from app.deps import CatalogDep, KeitaroDep, ReferencesDep, SessionDep, SettingsDep
from app.errors import AppError
from app.models import Campaign
from app.schemas import (
    CampaignCreate,
    CampaignImport,
    CampaignOut,
    CampaignShort,
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
    return [CampaignShort(id=c.id, keitaro_id=c.keitaro_id, name=c.name, geo=c.geo) for c in rows]


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
