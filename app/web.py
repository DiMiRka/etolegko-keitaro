import asyncio
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app import auth
from app import streams as svc
from app.deps import CatalogDep, SessionDep, SettingsDep
from app.errors import NotFound

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["asset_version"] = max(
    int(p.stat().st_mtime) for p in (Path(__file__).parent / "static").iterdir()
)
router = APIRouter(include_in_schema=False)


@router.get("/login")
async def login_page(request: Request, next: str = "/"):
    if request.state.user is not None:
        return RedirectResponse(auth.safe_next(next), status_code=303)
    return templates.TemplateResponse(request, "login.html", {"next": auth.safe_next(next), "error": None})


@router.post("/login")
async def login(request: Request, session: SessionDep, settings: SettingsDep):
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    username = (form.get("username") or [""])[0]
    password = (form.get("password") or [""])[0]
    target = auth.safe_next((form.get("next") or ["/"])[0])
    user = await auth.authenticate(session, username, password)
    if user is None:
        await asyncio.sleep(0.5)
        return templates.TemplateResponse(
            request, "login.html",
            {"next": target, "error": "Неверное имя пользователя или пароль", "username": username},
            status_code=401,
        )
    ttl = settings.session_ttl_hours * 3600
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        auth.COOKIE_NAME, auth.make_token(user, request.app.state.secret_key, ttl),
        max_age=ttl, httponly=True, samesite="lax", secure=settings.cookie_secure, path="/",
    )
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.COOKIE_NAME, path="/")
    return response


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


@router.get("/offers")
async def offers_page(request: Request):
    return templates.TemplateResponse(request, "offers.html", {"nav": "offers"})


@router.get("/offers/{offer_id}")
async def offer_page(request: Request, offer_id: int, catalog: CatalogDep):
    offer = await catalog.get(offer_id)
    if offer is None:
        raise NotFound(f"Оффер {offer_id} не найден в Keitaro")
    return templates.TemplateResponse(request, "offer.html", {"nav": "offers", "offer": offer})


@router.get("/campaigns/{campaign_id}")
async def campaign_page(request: Request, campaign_id: int, session: SessionDep, settings: SettingsDep):
    campaign = await svc.load_campaign(session, campaign_id)
    kt_url = f"{settings.keitaro_url.rstrip('/')}/admin/#!/campaign/{campaign.keitaro_id}"
    return templates.TemplateResponse(
        request, "campaign.html",
        {"nav": "campaigns", "campaign": campaign, "kt_url": kt_url, "prefix": settings.campaign_prefix},
    )
