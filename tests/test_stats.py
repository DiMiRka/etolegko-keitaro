import unittest
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app import stats

DAYS = ["2026-11-18", "2026-11-19", "2026-11-20"]


def row(stream, offer, day, clicks, unique=0, conv=0, revenue=0):
    return {
        "stream_id": stream, "offer_id": offer, "day": day, "clicks": clicks,
        "campaign_unique_clicks": unique, "conversions": conv, "revenue": revenue,
    }


class DayRangeTest(unittest.TestCase):
    def test_ends_today_in_tracker_timezone(self):
        late_utc = datetime(2026, 11, 19, 22, 30, tzinfo=UTC)
        moscow_now = late_utc.astimezone(ZoneInfo("Europe/Moscow"))
        self.assertEqual(stats.day_range(3, "Europe/Moscow", now=moscow_now), DAYS)

    def test_single_day(self):
        now = datetime(2026, 11, 20, 10, 0)
        self.assertEqual(stats.day_range(1, "Europe/Moscow", now=now), ["2026-11-20"])


class ReportBodyTest(unittest.TestCase):
    def test_body(self):
        body = stats.report_body(215444, DAYS, "Europe/Moscow")
        self.assertEqual(body["range"], {"from": "2026-11-18", "to": "2026-11-20", "timezone": "Europe/Moscow"})
        self.assertEqual(body["dimensions"], ["stream_id", "offer_id", "day"])
        self.assertEqual(body["filters"], [{"name": "campaign_id", "operator": "EQUALS", "expression": 215444}])
        self.assertIn("clicks", body["measures"])


class AggregateTest(unittest.TestCase):
    def setUp(self):
        self.result = stats.aggregate([
            row(10, 0, "2026-11-19", 100, unique=40),
            row(10, 0, "2026-11-20", 5),
            row(11, 1, "2026-11-18", 8, conv=2, revenue=10.5),
            row(11, 1, "2026-11-20", 2, revenue=1.25),
            row(11, 2, "2026-11-20", 10, unique=3),
            row(11, 2, "2026-11-01", 999),
        ], DAYS)

    def test_total(self):
        t = self.result["total"]
        self.assertEqual(t["clicks"], 125)
        self.assertEqual(t["unique_clicks"], 43)
        self.assertEqual(t["conversions"], 2)
        self.assertEqual(t["revenue"], 11.75)
        self.assertEqual(t["by_day"], [8, 100, 17])
        self.assertEqual(t["today"], 17)
        self.assertEqual(t["cr"], 1.6)

    def test_streams(self):
        geo, offers = self.result["streams"][10], self.result["streams"][11]
        self.assertEqual((geo["clicks"], geo["today"], geo["offers"]), (105, 5, {}))
        self.assertEqual(offers["by_day"], [8, 0, 12])

    def test_offers(self):
        offers = self.result["streams"][11]["offers"]
        self.assertEqual(offers[1]["by_day"], [8, 0, 2])
        self.assertEqual(offers[1]["cr"], 20.0)
        self.assertEqual(offers[2]["clicks"], 10)

    def test_today_unique_and_bots(self):
        r = stats.aggregate([
            {"stream_id": 10, "offer_id": 0, "day": "2026-11-20", "clicks": 9, "stream_unique_clicks": 4, "bots": 2},
            {"stream_id": 10, "offer_id": 0, "day": "2026-11-19", "clicks": 5, "stream_unique_clicks": 5, "bots": 1},
        ], DAYS)
        s = r["streams"][10]
        self.assertEqual((s["today"], s["today_unique"], s["today_bots"]), (9, 4, 2))
        self.assertEqual((s["bots"], s["stream_unique_clicks"]), (3, 9))
        self.assertNotIn("_bots_day", s)

    def test_rows_outside_range_ignored(self):
        self.assertNotIn(999, self.result["total"]["by_day"])

    def test_empty(self):
        r = stats.aggregate([], DAYS)
        self.assertEqual(r["total"]["by_day"], [0, 0, 0])
        self.assertEqual((r["total"]["cr"], r["streams"]), (0.0, {}))


if __name__ == "__main__":
    unittest.main()
