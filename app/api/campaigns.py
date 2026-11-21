from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CatalogDep, Days, KeitaroDep, ReferencesDep, SessionDep, SettingsDep
from app.models import Campaign
from app.schemas import (
    CampaignCreate,
    CampaignImport,
    CampaignOut,
    CampaignSettingsUpdate,
    CampaignShort,
    CampaignUpdate,
    StateIn,
)
from app.services import audit, stats
from app.services import campaigns as campaign_svc
from app.services import streams as stream_svc
from app.services.campaigns import Tracking

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


@router.get("", response_model=list[CampaignShort])
async def list_campaigns(session: SessionDep):
    rows = await session.scalars(select(Campaign).order_by(Campaign.id.desc()))
    return [CampaignShort.of(c) for c in rows]


@router.get("/stats")
async def campaigns_stats(session: SessionDep, kt: KeitaroDep, settings: SettingsDep, days: Days = 7):
    ids = list(await session.scalars(select(Campaign.keitaro_id)))
    return {
        "days": days,
        "campaigns": await stats.campaigns_totals(kt, ids, days, settings.keitaro_timezone),
    }


@router.post("", response_model=CampaignOut, status_code=201)
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
    campaign = await campaign_svc.create_campaign(
        session, kt, catalog, settings, body.name, body.geo, body.offer_id, tracking
    )
    return CampaignOut.of(campaign)


@router.post("/import", response_model=CampaignOut)
async def import_campaign(body: CampaignImport, session: SessionDep, kt: KeitaroDep):
    campaign = await stream_svc.import_campaign(session, kt, body.keitaro_id)
    return CampaignOut.of(await stream_svc.fetch_streams(session, kt, campaign))


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: int, session: SessionDep):
    return CampaignOut.of(await stream_svc.load_campaign(session, campaign_id))


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: int,
    body: CampaignUpdate,
    session: SessionDep,
    kt: KeitaroDep,
    references: ReferencesDep,
    settings: SettingsDep,
):
    campaign = await stream_svc.load_campaign(session, campaign_id)
    await references.check(body.domain_id, body.group_id, body.traffic_source_id)
    updated = await campaign_svc.update_campaign(
        session, kt, settings, campaign, body.name, body.geo,
        body.domain_id, body.group_id, body.traffic_source_id,
    )
    return CampaignOut.of(updated)


@router.delete("/{campaign_id}", status_code=204)
async def forget_campaign(campaign_id: int, session: SessionDep):
    await stream_svc.forget_campaign(session, await stream_svc.load_campaign(session, campaign_id))


@router.post("/{campaign_id}/state", response_model=CampaignOut)
async def set_campaign_state(campaign_id: int, body: StateIn, session: SessionDep, kt: KeitaroDep):
    campaign = await stream_svc.load_campaign(session, campaign_id)
    return CampaignOut.of(await campaign_svc.set_state(session, kt, campaign, body.active))


@router.get("/{campaign_id}/settings")
async def get_campaign_settings(campaign_id: int, session: SessionDep, kt: KeitaroDep):
    return await campaign_svc.campaign_settings(kt, await stream_svc.load_campaign(session, campaign_id))


@router.patch("/{campaign_id}/settings")
async def update_campaign_settings(
    campaign_id: int, body: CampaignSettingsUpdate, session: SessionDep, kt: KeitaroDep
):
    campaign = await stream_svc.load_campaign(session, campaign_id)
    return await campaign_svc.update_settings(session, kt, campaign, body.model_dump(exclude_none=True))


@router.get("/{campaign_id}/log")
async def campaign_log(campaign_id: int, session: SessionDep):
    await stream_svc.load_campaign(session, campaign_id)
    return await audit.history(session, campaign_id)


@router.get("/{campaign_id}/stats")
async def campaign_stats(campaign_id: int, session: SessionDep, kt: KeitaroDep, settings: SettingsDep, days: Days = 7):
    campaign = await stream_svc.load_campaign(session, campaign_id)
    return await stats.campaign_stats(kt, campaign.keitaro_id, days, settings.keitaro_timezone)


@router.post("/{campaign_id}/fetch", response_model=CampaignOut)
async def fetch_streams(campaign_id: int, session: SessionDep, kt: KeitaroDep):
    campaign = await stream_svc.load_campaign(session, campaign_id)
    return CampaignOut.of(await stream_svc.fetch_streams(session, kt, campaign))
