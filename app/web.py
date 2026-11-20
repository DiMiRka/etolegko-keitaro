from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import streams as svc
from app.deps import SessionDep, SettingsDep

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["asset_version"] = max(
    int(p.stat().st_mtime) for p in (Path(__file__).parent / "static").iterdir()
)
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
    campaign = await svc.load_campaign(session, campaign_id)
    kt_url = f"{settings.keitaro_url.rstrip('/')}/admin/#!/campaign/{campaign.keitaro_id}"
    return templates.TemplateResponse(
        request, "campaign.html",
        {"nav": "campaigns", "campaign": campaign, "kt_url": kt_url, "prefix": settings.campaign_prefix},
    )
