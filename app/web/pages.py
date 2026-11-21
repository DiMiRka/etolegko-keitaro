from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.api.deps import CatalogDep, SessionDep, SettingsDep
from app.core.errors import NotFound
from app.services import streams as stream_svc
from app.web.templating import templates

router = APIRouter(include_in_schema=False)


@router.get("/")
async def index():
    return RedirectResponse("/campaigns", status_code=302)


@router.get("/campaigns")
async def campaigns_page(request: Request):
    return templates.TemplateResponse(request, "campaigns.html", {"nav": "campaigns"})


@router.get("/campaigns/new")
async def new_campaign_page(request: Request, settings: SettingsDep):
    return templates.TemplateResponse(
        request, "campaign_new.html", {"nav": "campaigns", "prefix": settings.campaign_prefix}
    )


@router.get("/campaigns/{campaign_id}")
async def campaign_page(request: Request, campaign_id: int, session: SessionDep, settings: SettingsDep):
    campaign = await stream_svc.load_campaign(session, campaign_id)
    kt_url = f"{settings.keitaro_url.rstrip('/')}/admin/#!/campaign/{campaign.keitaro_id}"
    return templates.TemplateResponse(
        request, "campaign.html",
        {"nav": "campaigns", "campaign": campaign, "kt_url": kt_url, "prefix": settings.campaign_prefix},
    )


@router.get("/offers")
async def offers_page(request: Request):
    return templates.TemplateResponse(request, "offers.html", {"nav": "offers"})


@router.get("/offers/{offer_id}")
async def offer_page(request: Request, offer_id: int, catalog: CatalogDep):
    offer = await catalog.get(offer_id)
    if offer is None:
        raise NotFound(f"Оффер {offer_id} не найден в Keitaro")
    return templates.TemplateResponse(request, "offer.html", {"nav": "offers", "offer": offer})
