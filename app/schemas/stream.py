from pydantic import BaseModel, Field

from app.models import Stream, StreamOffer


class OfferAdd(BaseModel):
    offer_id: int


class PinIn(BaseModel):
    pinned: bool
    share: int | None = Field(default=None, ge=0, le=100)


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
