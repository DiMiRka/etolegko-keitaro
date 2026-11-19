from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app import streams as svc
from app.config import Settings
from app.deps import get_session, settings_dep

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
router = APIRouter(include_in_schema=False)


@router.get("/")
async def index(request: Request, settings: Settings = Depends(settings_dep)):
    return templates.TemplateResponse(request, "index.html", {"prefix": settings.campaign_prefix})


@router.get("/campaigns/{campaign_id}")
async def campaign_page(
    request: Request,
    campaign_id: int,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
):
    campaign = await svc.load_campaign(session, campaign_id)
    kt_url = f"{settings.keitaro_url.rstrip('/')}/admin/#!/campaign/{campaign.keitaro_id}"
    return templates.TemplateResponse(request, "campaign.html", {"campaign": campaign, "kt_url": kt_url})
