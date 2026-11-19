from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import campaigns
from app import streams as svc
from app.config import Settings
from app.deps import get_catalog, get_keitaro, get_session, settings_dep
from app.errors import AppError
from app.keitaro import KeitaroClient
from app.models import Campaign
from app.offers import OfferCatalog
from app.schemas import (
    CampaignCreate, CampaignImport, CampaignOut, CampaignShort, OfferAdd, OfferOut, PinIn, StreamOut,
)

router = APIRouter(prefix="/api")


@router.get("/offers", response_model=list[OfferOut])
async def search_offers(q: str = "", catalog: OfferCatalog = Depends(get_catalog)):
    return await catalog.search(q)


@router.get("/campaigns", response_model=list[CampaignShort])
async def list_campaigns(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(select(Campaign).order_by(Campaign.id.desc()))
    return [CampaignShort(id=c.id, keitaro_id=c.keitaro_id, name=c.name, geo=c.geo) for c in rows]


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
async def create_campaign(
    body: CampaignCreate,
    session: AsyncSession = Depends(get_session),
    kt: KeitaroClient = Depends(get_keitaro),
    catalog: OfferCatalog = Depends(get_catalog),
    settings: Settings = Depends(settings_dep),
):
    campaign = await campaigns.create_campaign(
        session, kt, catalog, settings, body.name, body.geo, body.offer_id
    )
    return CampaignOut.of(campaign)


@router.post("/campaigns/import", response_model=CampaignOut)
async def import_campaign(
    body: CampaignImport,
    session: AsyncSession = Depends(get_session),
    kt: KeitaroClient = Depends(get_keitaro),
):
    campaign = await svc.import_campaign(session, kt, body.keitaro_id)
    return CampaignOut.of(await svc.fetch_streams(session, kt, campaign))


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    return CampaignOut.of(await svc.load_campaign(session, campaign_id))


@router.post("/campaigns/{campaign_id}/fetch", response_model=CampaignOut)
async def fetch_streams(
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
    kt: KeitaroClient = Depends(get_keitaro),
):
    campaign = await svc.load_campaign(session, campaign_id)
    return CampaignOut.of(await svc.fetch_streams(session, kt, campaign))


@router.post("/streams/{stream_id}/offers", response_model=StreamOut)
async def add_offer(
    stream_id: int,
    body: OfferAdd,
    session: AsyncSession = Depends(get_session),
    catalog: OfferCatalog = Depends(get_catalog),
):
    stream = await svc.load_stream(session, stream_id)
    offer = await catalog.get(body.offer_id)
    if offer is None:
        raise AppError(f"Оффер {body.offer_id} не найден в Keitaro")
    await svc.add_offer(session, stream, body.offer_id, offer["name"])
    return StreamOut.of(stream)


@router.post("/streams/{stream_id}/offers/{offer_id}/remove", response_model=StreamOut)
async def remove_offer(stream_id: int, offer_id: int, session: AsyncSession = Depends(get_session)):
    stream = await svc.load_stream(session, stream_id)
    await svc.remove_offer(session, stream, svc.find_offer(stream, offer_id))
    return StreamOut.of(stream)


@router.post("/streams/{stream_id}/offers/{offer_id}/bring-back", response_model=StreamOut)
async def bring_back(stream_id: int, offer_id: int, session: AsyncSession = Depends(get_session)):
    stream = await svc.load_stream(session, stream_id)
    await svc.bring_back(session, stream, svc.find_offer(stream, offer_id))
    return StreamOut.of(stream)


@router.post("/streams/{stream_id}/offers/{offer_id}/pin", response_model=StreamOut)
async def pin_offer(stream_id: int, offer_id: int, body: PinIn, session: AsyncSession = Depends(get_session)):
    stream = await svc.load_stream(session, stream_id)
    await svc.set_pin(session, stream, svc.find_offer(stream, offer_id), body.pinned, body.share)
    return StreamOut.of(stream)


@router.post("/streams/{stream_id}/cancel", response_model=StreamOut)
async def cancel(stream_id: int, session: AsyncSession = Depends(get_session)):
    stream = await svc.load_stream(session, stream_id)
    await svc.cancel(session, stream)
    return StreamOut.of(stream)


@router.post("/streams/{stream_id}/push", response_model=StreamOut)
async def push(
    stream_id: int,
    session: AsyncSession = Depends(get_session),
    kt: KeitaroClient = Depends(get_keitaro),
):
    stream = await svc.load_stream(session, stream_id)
    await svc.push(session, kt, stream)
    return StreamOut.of(stream)
