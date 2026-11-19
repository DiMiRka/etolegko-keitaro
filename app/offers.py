import asyncio
import time

from app.keitaro import KeitaroClient


class OfferCatalog:
    def __init__(self, kt: KeitaroClient, ttl: float = 60.0):
        self._kt = kt
        self._ttl = ttl
        self._items: list[dict] = []
        self._loaded_at: float | None = None
        self._lock = asyncio.Lock()

    async def all(self) -> list[dict]:
        async with self._lock:
            if self._loaded_at is None or time.monotonic() - self._loaded_at > self._ttl:
                raw = await self._kt.list_offers()
                self._items = [
                    {"id": o["id"], "name": o.get("name") or "", "state": o.get("state", "active")}
                    for o in raw
                ]
                self._loaded_at = time.monotonic()
            return self._items

    async def search(self, q: str = "", limit: int = 20) -> list[dict]:
        q = q.strip().lower()
        items = [o for o in await self.all() if o["state"] == "active"]
        if q:
            items = [o for o in items if q in o["name"].lower() or str(o["id"]).startswith(q)]
        return items[:limit]

    async def get(self, offer_id: int) -> dict | None:
        return next((o for o in await self.all() if o["id"] == offer_id), None)
