from app.cache import CachedList
from app.keitaro import KeitaroClient


class OfferCatalog:
    def __init__(self, kt: KeitaroClient, ttl: float = 60.0):
        self._kt = kt
        self._cache = CachedList(self._load, ttl)

    async def _load(self) -> list[dict]:
        return [
            {"id": o["id"], "name": o.get("name") or "", "state": o.get("state", "active")}
            for o in await self._kt.list_offers()
        ]

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
