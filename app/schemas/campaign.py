from typing import Literal

from pydantic import BaseModel, Field

from app.models import Campaign
from app.schemas.stream import StreamOut


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    geo: str = Field(min_length=2, max_length=2)
    offer_id: int
    domain_id: int | None = None
    group_id: int | None = None
    traffic_source_id: int | None = None


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    geo: str | None = Field(default=None, min_length=2, max_length=2)
    domain_id: int | None = None
    group_id: int | None = None
    traffic_source_id: int | None = None


class CampaignSettingsUpdate(BaseModel):
    cost_type: Literal["CPC", "CPUC", "CPM"] | None = None
    cost_value: float | None = Field(default=None, ge=0)
    cost_currency: Literal["USD", "EUR", "RUB", "UAH", "GBP"] | None = None
    cost_auto: bool | None = None
    traffic_loss: float | None = Field(default=None, ge=0, lt=100)
    notes: str | None = Field(default=None, max_length=5000)


class CampaignImport(BaseModel):
    keitaro_id: int


class CampaignImportMany(BaseModel):
    group_id: int | None = None


class CampaignShort(BaseModel):
    id: int
    keitaro_id: int
    name: str
    geo: str | None
    group_id: int | None
    state: str | None
    url: str | None

    @classmethod
    def of(cls, c: Campaign) -> "CampaignShort":
        return cls(
            id=c.id, keitaro_id=c.keitaro_id, name=c.name, geo=c.geo,
            group_id=c.group_id, state=c.state, url=c.url,
        )


class CampaignOut(BaseModel):
    id: int
    keitaro_id: int
    name: str
    alias: str
    geo: str | None
    domain_id: int | None
    group_id: int | None
    traffic_source_id: int | None
    state: str | None
    url: str | None
    streams: list[StreamOut]

    @classmethod
    def of(cls, c: Campaign) -> "CampaignOut":
        return cls(
            id=c.id, keitaro_id=c.keitaro_id, name=c.name, alias=c.alias, geo=c.geo,
            domain_id=c.domain_id, group_id=c.group_id, traffic_source_id=c.traffic_source_id,
            state=c.state, url=c.url, streams=[StreamOut.of(s) for s in c.streams],
        )
