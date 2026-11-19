from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import router as api_router
from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.deps import get_session
from app.errors import AppError, NotFound
from app.keitaro import KeitaroClient, KeitaroError
from app.offers import OfferCatalog


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.keitaro = KeitaroClient(
        settings.keitaro_url,
        settings.keitaro_api_key,
        user_agent=settings.keitaro_user_agent,
        timeout=settings.keitaro_timeout,
    )
    app.state.catalog = OfferCatalog(app.state.keitaro)
    yield
    await app.state.keitaro.aclose()
    await engine.dispose()


app = FastAPI(title="Keitaro wrapper", lifespan=lifespan)
app.include_router(api_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse({"detail": str(exc)}, status_code=404 if isinstance(exc, NotFound) else 400)


@app.exception_handler(KeitaroError)
async def keitaro_error_handler(request: Request, exc: KeitaroError):
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
