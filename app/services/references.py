from app.core.cache import CachedList
from app.core.errors import AppError
from app.keitaro import KeitaroClient


def _active(items: list[dict]) -> list[dict]:
    return [
        {"id": i["id"], "name": i.get("name") or str(i["id"])}
        for i in items
        if i.get("state", "active") == "active"
    ]


class References:
    def __init__(self, kt: KeitaroClient, ttl: float = 300.0):
        self._kt = kt
        self._domains = CachedList(lambda: self._fetch(kt.list_domains), ttl)
        self._groups = CachedList(lambda: self._fetch(kt.list_campaign_groups), ttl)
        self._sources = CachedList(lambda: self._fetch(kt.list_traffic_sources), ttl)

    @staticmethod
    async def _fetch(load) -> list[dict]:
        return _active(await load())

    async def all(self) -> dict[str, list[dict]]:
        return {
            "domains": await self._domains.get(),
            "groups": sorted(await self._groups.get(), key=lambda g: g["name"].lower()),
            "traffic_sources": await self._sources.get(),
        }

    async def create_group(self, name: str) -> dict:
        name = name.strip()
        if not name:
            raise AppError("Укажите название группы")
        self._groups.invalidate()
        existing = next((g for g in await self._groups.get() if g["name"].lower() == name.lower()), None)
        if existing is not None:
            raise AppError(f"Группа «{existing['name']}» уже есть (#{existing['id']}), выберите её в списке")
        created = await self._kt.create_campaign_group(name)
        self._groups.invalidate()
        return {"id": created["id"], "name": created.get("name") or name}

    async def check(
        self, domain_id: int | None = None, group_id: int | None = None, traffic_source_id: int | None = None
    ) -> None:
        refs = await self.all()
        for key, value, label in (
            ("domains", domain_id, "Домен"),
            ("groups", group_id, "Группа"),
            ("traffic_sources", traffic_source_id, "Источник"),
        ):
            if value is not None and not any(i["id"] == value for i in refs[key]):
                raise AppError(f"{label} {value} не найден в Keitaro")
