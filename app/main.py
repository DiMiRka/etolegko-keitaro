from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import make_engine, make_sessionmaker
from app.deps import get_session
from app.keitaro import KeitaroClient


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
    yield
    await app.state.keitaro.aclose()
    await engine.dispose()


app = FastAPI(title="Keitaro wrapper", lifespan=lifespan)


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
