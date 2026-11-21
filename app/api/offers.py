from fastapi import APIRouter

from app.api.deps import CatalogDep, Days, KeitaroDep, SessionDep, SettingsDep
from app.core.errors import NotFound
from app.keitaro import KeitaroError
from app.schemas import OfferOut
from app.services import stats
from app.services.offers import offer_usage

router = APIRouter(prefix="/offers", tags=["offers"])


@router.get("", response_model=list[OfferOut])
async def search_offers(catalog: CatalogDep, q: str = ""):
    return await catalog.search(q)


@router.get("/catalog")
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


@router.get("/{offer_id}")
async def offer_detail(offer_id: int, session: SessionDep, catalog: CatalogDep):
    offer = await catalog.get(offer_id)
    if offer is None:
        raise NotFound(f"Оффер {offer_id} не найден в Keitaro")
    return {**offer, "usage": await offer_usage(session, offer_id)}


@router.get("/{offer_id}/stats")
async def offer_stats(offer_id: int, kt: KeitaroDep, catalog: CatalogDep, settings: SettingsDep, days: Days = 7):
    if await catalog.get(offer_id) is None:
        raise NotFound(f"Оффер {offer_id} не найден в Keitaro")
    return await stats.offer_stats(kt, offer_id, days, settings.keitaro_timezone)
