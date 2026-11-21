import asyncio
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.api.deps import SessionDep, SettingsDep
from app.core import security
from app.services import users
from app.web.templating import templates

router = APIRouter(include_in_schema=False)


@router.get("/login")
async def login_page(request: Request, next: str = "/"):
    target = security.safe_next(next)
    if request.state.user is not None:
        return RedirectResponse(target, status_code=303)
    return templates.TemplateResponse(request, "login.html", {"next": target, "error": None})


@router.post("/login")
async def login(request: Request, session: SessionDep, settings: SettingsDep):
    form = parse_qs((await request.body()).decode(), keep_blank_values=True)
    username = (form.get("username") or [""])[0]
    password = (form.get("password") or [""])[0]
    target = security.safe_next((form.get("next") or ["/"])[0])
    user = await users.authenticate(session, username, password)
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
        security.COOKIE_NAME, security.make_token(user, request.app.state.secret_key, ttl),
        max_age=ttl, httponly=True, samesite="lax", secure=settings.cookie_secure, path="/",
    )
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(security.COOKIE_NAME, path="/")
    return response
