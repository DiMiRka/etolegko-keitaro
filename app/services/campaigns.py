import re
import secrets
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.keitaro import KeitaroClient, KeitaroError
from app.models import Campaign
from app.services import audit
from app.services.offers import OfferCatalog
from app.services.streams import apply_campaign_info, fetch_streams, load_campaign

GEO_RE = re.compile(r"^[A-Z]{2}$")


def full_name(name: str, prefix: str) -> str:
    name = name.strip()
    if not name:
        raise AppError("Укажите название кампании")
    return name if name.startswith(prefix) else prefix + name


def normalize_geo(geo: str) -> str:
    geo = geo.strip().upper()
    if not GEO_RE.match(geo):
        raise AppError("Гео: двухбуквенный код страны, например AU")
    return geo


def make_alias(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return f"{slug}-{secrets.token_hex(3)}"


@dataclass(frozen=True)
class Tracking:
    domain_id: int
    group_id: int
    traffic_source_id: int

    @classmethod
    def defaults(cls, settings: Settings) -> "Tracking":
        return cls(settings.keitaro_domain_id, settings.keitaro_group_id, settings.keitaro_traffic_source_id)


def campaign_payload(name: str, alias: str, tracking: Tracking) -> dict:
    return {
        "name": name,
        "alias": alias,
        "type": "position",
        "state": "active",
        "cost_type": "CPC",
        "cost_value": 0,
        "cost_currency": "USD",
        "cost_auto": True,
        "domain_id": tracking.domain_id,
        "group_id": tracking.group_id,
        "traffic_source_id": tracking.traffic_source_id,
    }


def geo_stream_payload(campaign_id: int, geo: str, redirect_url: str) -> dict:
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": geo_stream_name(geo),
        "position": 1,
        "state": "active",
        "schema": "redirect",
        "action_type": "http",
        "action_payload": redirect_url,
        "collect_clicks": True,
        "filters": [{"name": "country", "mode": "accept", "payload": [geo]}],
    }


def offer_stream_payload(campaign_id: int, offer_id: int) -> dict:
    return {
        "campaign_id": campaign_id,
        "type": "regular",
        "name": "Offers",
        "position": 2,
        "state": "active",
        "schema": "landings",
        "action_type": "http",
        "collect_clicks": True,
        "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
    }


async def create_campaign(
    session: AsyncSession,
    kt: KeitaroClient,
    catalog: OfferCatalog,
    settings: Settings,
    name: str,
    geo: str,
    offer_id: int,
    tracking: Tracking | None = None,
) -> Campaign:
    name = full_name(name, settings.campaign_prefix)
    geo = normalize_geo(geo)
    if await catalog.get(offer_id) is None:
        raise AppError(f"Оффер {offer_id} не найден в Keitaro")
    tracking = tracking or Tracking.defaults(settings)

    created = await kt.create_campaign(campaign_payload(name, make_alias(name), tracking))
    campaign_id = created["id"]
    try:
        await kt.create_stream(geo_stream_payload(campaign_id, geo, settings.geo_redirect_url))
        await kt.create_stream(offer_stream_payload(campaign_id, offer_id))
    except KeitaroError as e:
        try:
            await kt.delete_campaign(campaign_id)
        except KeitaroError:
            raise AppError(f"Не удалось создать потоки ({e}), кампания {campaign_id} осталась в Keitaro") from e
        raise AppError(f"Не удалось создать потоки, кампания удалена: {e}") from e

    campaign = Campaign(
        keitaro_id=campaign_id,
        name=created["name"],
        alias=created["alias"],
        geo=geo,
        domain_id=tracking.domain_id,
        group_id=tracking.group_id,
        traffic_source_id=tracking.traffic_source_id,
    )
    session.add(campaign)
    await session.flush()
    audit.record(
        session, campaign.id, "create",
        f"Кампания создана в Keitaro: гео {geo} → google.com, остальные → оффер {offer_id}",
        details={"geo": geo, "offer_id": offer_id, "domain_id": tracking.domain_id,
                 "group_id": tracking.group_id, "traffic_source_id": tracking.traffic_source_id},
    )
    await session.commit()
    campaign = await load_campaign(session, campaign.id)
    return await fetch_streams(session, kt, campaign, log=False)


SETTINGS_LABELS = {
    "cost_type": "модель затрат",
    "cost_value": "стоимость",
    "cost_currency": "валюта",
    "cost_auto": "стоимость из параметра cost",
    "traffic_loss": "% потерь",
    "uniqueness_method": "уникальность",
    "uniqueness_param": "параметр уникальности",
    "uniqueness_use_cookies": "уникальность по cookies",
    "cookies_ttl": "срок уникальности, ч",
    "notes": "заметки",
}


def _settings_of(info: dict) -> dict:
    data = {key: info.get(key) for key in SETTINGS_LABELS}
    data["uniqueness_param"] = data["uniqueness_param"] or ""
    data["notes"] = data["notes"] or ""
    data["type"] = info.get("type")
    return data


async def campaign_settings(kt: KeitaroClient, campaign: Campaign) -> dict:
    return _settings_of(await kt.get_campaign(campaign.keitaro_id))


def _same(a, b) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float) and not isinstance(a, bool):
        return float(a) == float(b)
    return a == b


async def update_settings(session: AsyncSession, kt: KeitaroClient, campaign: Campaign, changes: dict) -> dict:
    current = await campaign_settings(kt, campaign)
    diff = {k: v for k, v in changes.items() if v is not None and not _same(current.get(k), v)}
    method = diff.get("uniqueness_method", current["uniqueness_method"])
    param = diff.get("uniqueness_param", current["uniqueness_param"])
    if method == "param" and not (param or "").strip():
        raise AppError("Для уникальности по параметру укажите имя параметра")
    if not diff:
        return current
    await kt.update_campaign(campaign.keitaro_id, diff)

    def show(key, value):
        if key == "notes":
            return f"{len(value or '')} симв."
        if isinstance(value, bool):
            return "да" if value else "нет"
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value if value not in (None, "") else "—"

    message = ", ".join(f"{SETTINGS_LABELS[k]}: {show(k, current.get(k))} → {show(k, v)}" for k, v in diff.items())
    audit.record(session, campaign.id, "settings", f"Изменено в Keitaro: {message}",
                 details={"before": {k: current.get(k) for k in diff}, "after": diff})
    await session.commit()
    return await campaign_settings(kt, campaign)


async def set_state(session: AsyncSession, kt: KeitaroClient, campaign: Campaign, active: bool) -> Campaign:
    if active:
        await kt.enable_campaign(campaign.keitaro_id)
    else:
        await kt.disable_campaign(campaign.keitaro_id)
    apply_campaign_info(campaign, await kt.get_campaign(campaign.keitaro_id))
    audit.record(
        session, campaign.id, "campaign_state",
        "Кампания включена" if campaign.state == "active" else "Кампания выключена",
    )
    await session.commit()
    return await load_campaign(session, campaign.id)


def country_filter(stream: dict) -> dict | None:
    return next((f for f in stream.get("filters") or [] if f.get("name") == "country"), None)


def geo_stream_name(geo: str) -> str:
    return f"{geo} -> Google"


async def update_campaign(
    session: AsyncSession,
    kt: KeitaroClient,
    settings: Settings,
    campaign: Campaign,
    name: str | None = None,
    geo: str | None = None,
    domain_id: int | None = None,
    group_id: int | None = None,
    traffic_source_id: int | None = None,
) -> Campaign:
    new_name = full_name(name, settings.campaign_prefix) if name is not None else None
    new_geo = normalize_geo(geo) if geo is not None else None

    campaign_changes: dict = {}
    if new_name is not None and new_name != campaign.name:
        campaign_changes["name"] = new_name
    for field, value in (
        ("domain_id", domain_id), ("group_id", group_id), ("traffic_source_id", traffic_source_id)
    ):
        if value is not None and value != getattr(campaign, field):
            campaign_changes[field] = value

    geo_stream = None
    if new_geo is not None and new_geo != campaign.geo:
        kt_streams = sorted(await kt.list_streams(campaign.keitaro_id), key=lambda s: s.get("position") or 0)
        geo_stream = next((s for s in kt_streams if country_filter(s)), None)
        if geo_stream is None:
            raise AppError("В кампании нет потока с фильтром по стране, гео поменять нельзя")

    if campaign_changes:
        await kt.update_campaign(campaign.keitaro_id, campaign_changes)
        before = {k: getattr(campaign, k) for k in campaign_changes}
        labels = {"name": "название", "domain_id": "домен", "group_id": "группа", "traffic_source_id": "источник"}
        changed = ", ".join(f"{labels[k]}: {before[k]} → {v}" for k, v in campaign_changes.items())
        audit.record(session, campaign.id, "update", f"Изменено в Keitaro: {changed}",
                     details={"before": before, "after": campaign_changes})

    if geo_stream is not None:
        filters = []
        for f in geo_stream["filters"]:
            item = {"id": f["id"], "name": f["name"], "mode": f["mode"], "payload": f["payload"]}
            if f is country_filter(geo_stream):
                item["payload"] = [new_geo]
            filters.append(item)
        payload: dict = {"filters": filters}
        old = (country_filter(geo_stream)["payload"] or [""])[0]
        if geo_stream["name"] == geo_stream_name(old):
            payload["name"] = geo_stream_name(new_geo)
        await kt.update_stream(geo_stream["id"], payload)
        audit.record(session, campaign.id, "update", f"Изменено в Keitaro: гео {old} → {new_geo}",
                     details={"before": {"geo": old}, "after": {"geo": new_geo}})

    return await fetch_streams(session, kt, campaign, log=False)
