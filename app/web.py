from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app import streams as svc
from app.deps import SessionDep, SettingsDep

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter(include_in_schema=False)


@router.get("/")
async def index(request: Request, settings: SettingsDep):
    return templates.TemplateResponse(request, "index.html", {"prefix": settings.campaign_prefix})


@router.get("/campaigns/{campaign_id}")
async def campaign_page(request: Request, campaign_id: int, session: SessionDep, settings: SettingsDep):
    campaign = await svc.load_campaign(session, campaign_id)
    kt_url = f"{settings.keitaro_url.rstrip('/')}/admin/#!/campaign/{campaign.keitaro_id}"
    return templates.TemplateResponse(request, "campaign.html", {"campaign": campaign, "kt_url": kt_url})
