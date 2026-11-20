from pydantic import BaseModel, Field

from app.models import Campaign, Stream, StreamOffer


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


class CampaignState(BaseModel):
    active: bool


class CampaignImport(BaseModel):
    keitaro_id: int


class OfferAdd(BaseModel):
    offer_id: int


class PinIn(BaseModel):
    pinned: bool
    share: int | None = Field(default=None, ge=0, le=100)


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


class OfferOut(BaseModel):
    id: int
    name: str


class StreamOfferOut(BaseModel):
    offer_id: int
    offer_name: str
    share: int
    pinned: bool
    disabled: bool
    state: str
    is_dirty: bool

    @classmethod
    def of(cls, o: StreamOffer) -> "StreamOfferOut":
        return cls(
            offer_id=o.offer_id, offer_name=o.offer_name, share=o.share,
            pinned=o.pinned, disabled=o.disabled, state=o.state.value, is_dirty=o.is_dirty,
        )


class StreamOut(BaseModel):
    id: int
    keitaro_id: int
    name: str
    position: int
    has_offers: bool
    state: str | None
    is_dirty: bool
    last_error: str | None
    offers: list[StreamOfferOut]

    @classmethod
    def of(cls, s: Stream) -> "StreamOut":
        return cls(
            id=s.id, keitaro_id=s.keitaro_id, name=s.name, position=s.position,
            has_offers=s.has_offers, state=s.state, is_dirty=s.is_dirty, last_error=s.last_error,
            offers=[StreamOfferOut.of(o) for o in s.offers],
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
