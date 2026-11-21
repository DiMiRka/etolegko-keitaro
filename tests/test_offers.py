import unittest

from app.keitaro import KeitaroError
from app.services import stats
from tests.helpers import ApiCase
from tests.test_editor_api import EditorKeitaro
from tests.test_streams import CAMPAIGN_KT_ID, OFFER_STREAM_ID

DAYS = ["2026-11-19", "2026-11-20"]


class AggregateOfferTest(unittest.TestCase):
    def test_ranks_campaigns(self):
        r = stats.aggregate_offer([
            {"campaign_id": 1, "campaign": "a", "day": "2026-11-19", "clicks": 3},
            {"campaign_id": 2, "campaign": "b", "day": "2026-11-19", "clicks": 5, "conversions": 1},
            {"campaign_id": 1, "campaign": "a", "day": "2026-11-20", "clicks": 4},
            {"campaign_id": 3, "campaign": "c", "day": "2026-10-01", "clicks": 100},
        ], DAYS)
        self.assertEqual(r["total"]["by_day"], [8, 4])
        self.assertEqual([(c["keitaro_id"], c["clicks"]) for c in r["campaigns"]], [(1, 7), (2, 5)])
        self.assertEqual(r["campaigns"][1]["cr"], 20.0)


class OffersApiTest(ApiCase):
    def make_keitaro(self):
        return EditorKeitaro()

    def setUp(self):
        super().setUp()
        self.reports = []

        async def build_report(body):
            self.reports.append(body)
            if body["dimensions"] == ["offer_id"]:
                return {"rows": [{"offer_id": 2, "clicks": 12}, {"offer_id": 99, "clicks": 1}]}
            day = body["range"]["to"]
            return {"rows": [{"campaign_id": CAMPAIGN_KT_ID, "campaign": "x", "day": day, "clicks": 4}]}

        self.kt.build_report = build_report
        campaign = self.ok("POST", "/api/campaigns/import", json={"keitaro_id": CAMPAIGN_KT_ID})
        self.campaign_id = campaign["id"]
        sid = next(s["id"] for s in campaign["streams"] if s["keitaro_id"] == OFFER_STREAM_ID)
        self.ok("POST", f"/api/streams/{sid}/offers/3/remove")

    def test_catalog(self):
        rows = {o["id"]: o for o in self.ok("GET", "/api/offers/catalog")}
        self.assertEqual(sorted(rows), [1, 2, 3, 4, 5])
        self.assertEqual((rows[2]["clicks_7d"], rows[2]["campaigns_count"]), (12, 1))
        self.assertEqual((rows[3]["clicks_7d"], rows[3]["campaigns_count"]), (0, 0))
        self.assertEqual(rows[4]["campaigns_count"], 0)
        self.assertEqual(self.reports[-1]["filters"][0]["name"], "offer_id")

    def test_catalog_survives_report_error(self):
        async def broken(body):
            raise KeitaroError("Keitaro HTTP 500: boom", 500)

        self.kt.build_report = broken
        rows = self.ok("GET", "/api/offers/catalog")
        self.assertTrue(all(o["clicks_7d"] is None for o in rows))

    def test_detail_with_usage(self):
        offer = self.ok("GET", "/api/offers/3")
        self.assertEqual(offer["name"], "Offer 3")
        self.assertEqual(len(offer["usage"]), 1)
        u = offer["usage"][0]
        self.assertEqual(
            (u["campaign_id"], u["state"], u["share"], u["is_dirty"]), (self.campaign_id, "removed", 0, True)
        )
        self.assertEqual(self.ok("GET", "/api/offers/5")["usage"], [])
        self.ok("GET", "/api/offers/777", 404)

    def test_stats(self):
        data = self.ok("GET", "/api/offers/2/stats")
        self.assertEqual(data["total"]["today"], 4)
        self.assertEqual(data["campaigns"][0]["keitaro_id"], CAMPAIGN_KT_ID)
        self.assertEqual(self.reports[-1]["filters"], [{"name": "offer_id", "operator": "EQUALS", "expression": 2}])
        self.ok("GET", "/api/offers/777/stats", 404)

    def test_pages(self):
        r = self.client.get("/offers")
        self.assertEqual(r.status_code, 200)
        self.assertIn('href="/offers" class="menu-item active"', r.text)
        r = self.client.get("/offers/2")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Offer 2", r.text)
        self.assertEqual(self.client.get("/offers/777").status_code, 404)

    def test_autocomplete_still_returns_id_and_name(self):
        self.assertEqual(self.ok("GET", "/api/offers", params={"q": "offer 4"}), [{"id": 4, "name": "Offer 4"}])


if __name__ == "__main__":
    unittest.main()
