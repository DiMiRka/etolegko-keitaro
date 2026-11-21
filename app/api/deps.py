from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.keitaro import KeitaroClient
from app.services.offers import OfferCatalog
from app.services.references import References


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session


def get_keitaro(request: Request) -> KeitaroClient:
    return request.app.state.keitaro


def get_catalog(request: Request) -> OfferCatalog:
    return request.app.state.catalog


def get_references(request: Request) -> References:
    return request.app.state.references


def settings_dep() -> Settings:
    return get_settings()


SessionDep = Annotated[AsyncSession, Depends(get_session)]
KeitaroDep = Annotated[KeitaroClient, Depends(get_keitaro)]
CatalogDep = Annotated[OfferCatalog, Depends(get_catalog)]
SettingsDep = Annotated[Settings, Depends(settings_dep)]
ReferencesDep = Annotated[References, Depends(get_references)]
Days = Annotated[int, Query(ge=1, le=90)]
