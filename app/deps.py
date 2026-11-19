from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.keitaro import KeitaroClient
from app.offers import OfferCatalog


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_keitaro(request: Request) -> KeitaroClient:
    return request.app.state.keitaro


def get_catalog(request: Request) -> OfferCatalog:
    return request.app.state.catalog


def settings_dep() -> Settings:
    return get_settings()
