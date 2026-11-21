import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import auth
from app.api import router as api_router
from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.deps import SessionDep
from app.errors import AppError, Conflict, NotFound
from app.keitaro import KeitaroClient, KeitaroError
from app.offers import OfferCatalog
from app.references import References
from app.web import router as web_router

log = logging.getLogger("app")
PUBLIC_PATHS = {"/login", "/health"}


async def bootstrap_admin(sessionmaker, username: str, password: str) -> None:
    if not username or not password:
        return
    try:
        async with sessionmaker() as session:
            if await auth.users_count(session) == 0:
                await auth.create_user(session, username, password)
                log.warning("Создан первый пользователь %s из ADMIN_USERNAME / ADMIN_PASSWORD", username)
    except (SQLAlchemyError, AppError) as e:
        log.warning("Не удалось создать первого пользователя: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.secret_key = settings.secret_key or secrets.token_urlsafe(32)
    if not settings.secret_key:
        log.warning("SECRET_KEY не задан: сессии сбросятся при перезапуске")
    app.state.keitaro = KeitaroClient(
        settings.keitaro_url,
        settings.keitaro_api_key,
        user_agent=settings.keitaro_user_agent,
        timeout=settings.keitaro_timeout,
    )
    app.state.catalog = OfferCatalog(app.state.keitaro)
    app.state.references = References(app.state.keitaro)
    await bootstrap_admin(app.state.sessionmaker, settings.admin_username, settings.admin_password)
    yield
    await app.state.keitaro.aclose()
    await engine.dispose()


app = FastAPI(title="Keitaro wrapper", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
app.include_router(api_router)
app.include_router(web_router)


@app.middleware("http")
async def require_login(request: Request, call_next):
    path = request.url.path
    user = auth.read_token(request.cookies.get(auth.COOKIE_NAME), request.app.state.secret_key)
    request.state.user = user
    if user is None and path not in PUBLIC_PATHS and not path.startswith("/static/"):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Нужно войти в сервис"}, status_code=401)
        target = path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(target, safe='')}", status_code=303)
    token = auth.current_user.set(user)
    try:
        return await call_next(request)
    finally:
        auth.current_user.reset(token)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    status = 404 if isinstance(exc, NotFound) else 409 if isinstance(exc, Conflict) else 400
    return JSONResponse({"detail": str(exc)}, status_code=status)


@app.exception_handler(KeitaroError)
async def keitaro_error_handler(request: Request, exc: KeitaroError):
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.get("/health")
async def health(session: SessionDep) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
