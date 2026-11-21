import asyncio
import time
from collections.abc import Awaitable, Callable


class CachedList:
    def __init__(self, load: Callable[[], Awaitable[list[dict]]], ttl: float):
        self._load = load
        self._ttl = ttl
        self._items: list[dict] = []
        self._loaded_at: float | None = None
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        self._loaded_at = None

    async def get(self) -> list[dict]:
        async with self._lock:
            if self._loaded_at is None or time.monotonic() - self._loaded_at > self._ttl:
                self._items = await self._load()
                self._loaded_at = time.monotonic()
            return self._items
