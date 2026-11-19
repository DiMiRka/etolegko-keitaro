from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class OfferState(StrEnum):
    active = "active"
    removed = "removed"


def _enum(cls):
    return Enum(cls, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e])


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str] = mapped_column(String(255))
    geo: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    streams: Mapped[list["Stream"]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="Stream.position"
    )


class Stream(Base):
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    keitaro_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str] = mapped_column(String(255))
    position: Mapped[int] = mapped_column(default=0)
    has_offers: Mapped[bool] = mapped_column(default=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime | None]

    campaign: Mapped[Campaign] = relationship(back_populates="streams")
    offers: Mapped[list["StreamOffer"]] = relationship(
        back_populates="stream", cascade="all, delete-orphan", order_by="StreamOffer.id"
    )

    @property
    def is_dirty(self) -> bool:
        return any(o.is_dirty for o in self.offers)


class StreamOffer(Base):
    __tablename__ = "stream_offers"
    __table_args__ = (UniqueConstraint("stream_id", "offer_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey("streams.id", ondelete="CASCADE"), index=True)
    offer_id: Mapped[int]
    offer_name: Mapped[str] = mapped_column(String(500), default="")
    share: Mapped[int] = mapped_column(default=0)
    pinned: Mapped[bool] = mapped_column(default=False)
    state: Mapped[OfferState] = mapped_column(_enum(OfferState), default=OfferState.active)
    published_share: Mapped[int | None]
    published_state: Mapped[OfferState | None] = mapped_column(_enum(OfferState))

    stream: Mapped[Stream] = relationship(back_populates="offers")

    @property
    def is_dirty(self) -> bool:
        return self.share != self.published_share or self.state != self.published_state
