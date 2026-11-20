from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import CachedList
from app.keitaro import KeitaroClient
from app.models import Campaign, Stream, StreamOffer


def _offer(o: dict) -> dict:
    return {
        "id": o["id"],
        "name": o.get("name") or "",
        "state": o.get("state", "active"),
        "group": o.get("group") or "",
        "countries": o.get("country") or [],
        "payout_value": o.get("payout_value") or 0,
        "payout_currency": o.get("payout_currency") or "",
        "payout_type": o.get("payout_type") or "",
        "payout_auto": bool(o.get("payout_auto")),
        "offer_type": o.get("offer_type") or "",
        "action_type": o.get("action_type") or "",
        "notes": o.get("notes") or "",
        "created_at": o.get("created_at") or "",
    }


class OfferCatalog:
    def __init__(self, kt: KeitaroClient, ttl: float = 60.0):
        self._kt = kt
        self._cache = CachedList(self._load, ttl)

    async def _load(self) -> list[dict]:
        return [_offer(o) for o in await self._kt.list_offers()]

    async def all(self) -> list[dict]:
        return await self._cache.get()

    async def search(self, q: str = "", limit: int = 20) -> list[dict]:
        q = q.strip().lower()
        items = [o for o in await self.all() if o["state"] == "active"]
        if q:
            items = [o for o in items if q in o["name"].lower() or str(o["id"]).startswith(q)]
        return items[:limit]

    async def get(self, offer_id: int) -> dict | None:
        return next((o for o in await self.all() if o["id"] == offer_id), None)


async def offer_usage(session: AsyncSession, offer_id: int | None = None) -> list[dict]:
    query = (
        select(StreamOffer, Stream, Campaign)
        .join(Stream, StreamOffer.stream_id == Stream.id)
        .join(Campaign, Stream.campaign_id == Campaign.id)
        .order_by(Campaign.id.desc(), Stream.position)
    )
    if offer_id is not None:
        query = query.where(StreamOffer.offer_id == offer_id)
    rows = await session.execute(query)
    return [
        {
            "offer_id": so.offer_id,
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "stream_id": stream.id,
            "stream_name": stream.name,
            "stream_keitaro_id": stream.keitaro_id,
            "share": so.share,
            "state": so.state.value,
            "pinned": so.pinned,
            "disabled": so.disabled,
            "is_dirty": so.is_dirty,
        }
        for so, stream, campaign in rows
    ]
