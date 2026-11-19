from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import campaigns
from app.config import Settings
from app.deps import get_catalog, get_keitaro, get_session, settings_dep
from app.keitaro import KeitaroClient
from app.offers import OfferCatalog
from app.schemas import CampaignCreate, CampaignOut, OfferOut

router = APIRouter(prefix="/api")


@router.get("/offers", response_model=list[OfferOut])
async def search_offers(q: str = "", catalog: OfferCatalog = Depends(get_catalog)):
    return await catalog.search(q)


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
