from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.keitaro import KeitaroClient

MEASURES = ["clicks", "campaign_unique_clicks", "conversions", "revenue"]


def day_range(days: int, timezone: str, now: datetime | None = None) -> list[str]:
    today = (now or datetime.now(ZoneInfo(timezone))).date()
    return [(today - timedelta(days=n)).isoformat() for n in range(days - 1, -1, -1)]


def report_body(keitaro_id: int, days: list[str], timezone: str) -> dict:
    return {
        "range": {"from": days[0], "to": days[-1], "timezone": timezone},
        "dimensions": ["stream_id", "offer_id", "day"],
        "measures": MEASURES,
        "filters": [{"name": "campaign_id", "operator": "EQUALS", "expression": keitaro_id}],
    }


def _bucket(n: int) -> dict:
    return {"clicks": 0, "unique_clicks": 0, "conversions": 0, "revenue": 0.0, "by_day": [0] * n}


def _add(bucket: dict, row: dict, index: int) -> None:
    clicks = int(row.get("clicks") or 0)
    bucket["clicks"] += clicks
    bucket["unique_clicks"] += int(row.get("campaign_unique_clicks") or 0)
    bucket["conversions"] += int(row.get("conversions") or 0)
    bucket["revenue"] += float(row.get("revenue") or 0)
    bucket["by_day"][index] += clicks


def _finish(bucket: dict) -> dict:
    bucket["revenue"] = round(bucket["revenue"], 2)
    bucket["cr"] = round(bucket["conversions"] / bucket["clicks"] * 100, 2) if bucket["clicks"] else 0.0
    bucket["today"] = bucket["by_day"][-1]
    return bucket


def aggregate(rows: list[dict], days: list[str]) -> dict:
    index = {d: i for i, d in enumerate(days)}
    n = len(days)
    total = _bucket(n)
    streams: dict[int, dict] = {}

    for row in rows:
        i = index.get(str(row.get("day")))
        if i is None:
            continue
        _add(total, row, i)
        stream_id = int(row.get("stream_id") or 0)
        stream = streams.setdefault(stream_id, {**_bucket(n), "offers": {}})
        _add(stream, row, i)
        offer_id = int(row.get("offer_id") or 0)
        if offer_id:
            _add(stream["offers"].setdefault(offer_id, _bucket(n)), row, i)

    for stream in streams.values():
        _finish(stream)
        for offer in stream["offers"].values():
            _finish(offer)
    return {"days": days, "total": _finish(total), "streams": streams}


async def campaign_stats(kt: KeitaroClient, keitaro_id: int, days: int, timezone: str) -> dict:
    day_list = day_range(days, timezone)
    report = await kt.build_report(report_body(keitaro_id, day_list, timezone))
    return aggregate(report.get("rows") or [], day_list)
