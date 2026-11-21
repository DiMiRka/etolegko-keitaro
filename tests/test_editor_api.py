import unittest

from app.keitaro import KeitaroError
from tests.helpers import ApiCase
from tests.test_streams import CAMPAIGN_KT_ID, OFFER_STREAM_ID, FakeKeitaro


class EditorKeitaro(FakeKeitaro):
    async def get_campaign(self, campaign_id):
        if campaign_id == CAMPAIGN_KT_ID and not self.campaign_gone:
            return {"id": campaign_id, "name": "test_mironov_editor", "alias": "e"}
        raise KeitaroError("Keitaro HTTP 404: not found", 404)


class EditorApiTest(ApiCase):
    def make_keitaro(self):
        return EditorKeitaro()

    def setUp(self):
        super().setUp()
        campaign = self.ok("POST", "/api/campaigns/import", json={"keitaro_id": CAMPAIGN_KT_ID})
        self.campaign_id = campaign["id"]
        self.sid = next(s["id"] for s in campaign["streams"] if s["keitaro_id"] == OFFER_STREAM_ID)

    def shares(self, stream):
        return {o["offer_id"]: o["share"] for o in stream["offers"]}

    def test_full_cycle(self):
        base = f"/api/streams/{self.sid}"

        s = self.ok("POST", f"{base}/offers", json={"offer_id": 4})
        self.assertEqual(self.shares(s), {1: 25, 2: 25, 3: 25, 4: 25})
        self.assertTrue(s["is_dirty"])
        self.assertEqual(self.kt.kt_offers(), {1: 34, 2: 33, 3: 33})

        s = self.ok("POST", f"{base}/push")
        self.assertFalse(s["is_dirty"])
        self.assertEqual(self.kt.kt_offers(), {1: 25, 2: 25, 3: 25, 4: 25})

        s = self.ok("POST", f"{base}/offers/1/pin", json={"pinned": True})
        self.assertTrue(next(o for o in s["offers"] if o["offer_id"] == 1)["pinned"])

        s = self.ok("POST", f"{base}/offers/4/remove")
        self.assertEqual(self.shares(s), {1: 25, 2: 38, 3: 37, 4: 0})
        removed = next(o for o in s["offers"] if o["offer_id"] == 4)
        self.assertEqual(removed["state"], "removed")

        s = self.ok("POST", f"{base}/push")
        self.assertEqual(self.kt.kt_offers(), {1: 25, 2: 38, 3: 37})

        s = self.ok("POST", f"{base}/offers/4/bring-back")
        self.assertEqual(self.shares(s), {1: 25, 2: 25, 3: 25, 4: 25})
        s = self.ok("POST", f"{base}/cancel")
        self.assertEqual(self.shares(s), {1: 25, 2: 38, 3: 37, 4: 0})
        self.assertFalse(s["is_dirty"])

    def test_fetch_marks_deleted_in_keitaro(self):
        self.kt.streams[OFFER_STREAM_ID]["offers"].pop(0)
        c = self.ok("POST", f"/api/campaigns/{self.campaign_id}/fetch")
        stream = next(s for s in c["streams"] if s["id"] == self.sid)
        self.assertEqual(next(o for o in stream["offers"] if o["offer_id"] == 1)["state"], "removed")

    def test_errors(self):
        base = f"/api/streams/{self.sid}"
        self.ok("POST", f"{base}/offers", 400, json={"offer_id": 2})
        self.ok("POST", f"{base}/offers", 400, json={"offer_id": 999})
        self.ok("POST", f"{base}/offers/999/remove", 404)
        self.ok("POST", "/api/streams/12345/push", 404)
        self.ok("POST", f"{base}/offers/1/pin", 422, json={"pinned": True, "share": 101})
        self.kt.fail_update = True
        self.ok("POST", f"{base}/offers", json={"offer_id": 4})
        self.ok("POST", f"{base}/push", 400)
        s = self.ok("GET", f"/api/campaigns/{self.campaign_id}")
        stream = next(x for x in s["streams"] if x["id"] == self.sid)
        self.assertTrue(stream["is_dirty"])
        self.assertIn("boom", stream["last_error"])

    def test_pages_render(self):
        r = self.client.get("/", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (302, "/campaigns"))
        r = self.client.get("/campaigns")
        self.assertEqual(r.status_code, 200)
        self.assertIn('href="/campaigns/new"', r.text)
        r = self.client.get("/campaigns/new")
        self.assertEqual(r.status_code, 200)
        self.assertIn("create-form", r.text)
        r = self.client.get(f"/campaigns/{self.campaign_id}")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f"/admin/#!/campaign/{CAMPAIGN_KT_ID}", r.text)
        self.assertIn('value="test_mironov_editor"', r.text)
        self.assertEqual(self.client.get("/campaigns/999").status_code, 404)

    def test_forget_campaign(self):
        r = self.client.delete(f"/api/campaigns/{self.campaign_id}")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(self.ok("GET", "/api/campaigns"), [])
        self.ok("DELETE", f"/api/campaigns/{self.campaign_id}", 404)

    def test_fetch_of_gone_campaign_is_400(self):
        self.kt.campaign_gone = True
        r = self.ok("POST", f"/api/campaigns/{self.campaign_id}/fetch", 400)
        self.assertIn("больше нет в Keitaro", r["detail"])

    def test_stats(self):
        from app.stats import day_range

        today = day_range(1, "Europe/Moscow")[0]

        async def build_report(body):
            self.assertEqual(body["filters"][0]["expression"], CAMPAIGN_KT_ID)
            self.assertEqual(body["range"]["to"], today)
            return {"rows": [{"stream_id": OFFER_STREAM_ID, "offer_id": 2, "day": today, "clicks": 7}]}

        self.kt.build_report = build_report
        data = self.ok("GET", f"/api/campaigns/{self.campaign_id}/stats")
        self.assertEqual(len(data["days"]), 7)
        self.assertEqual(data["total"]["today"], 7)
        self.assertEqual(data["streams"][str(OFFER_STREAM_ID)]["offers"]["2"]["by_day"][-1], 7)
        self.ok("GET", f"/api/campaigns/{self.campaign_id}/stats", 422, params={"days": 0})

    def test_journal_and_stream_state_api(self):
        self.ok("POST", f"/api/streams/{self.sid}/offers", json={"offer_id": 4})
        s = self.ok("POST", f"/api/streams/{self.sid}/state", json={"active": False})
        self.assertEqual(s["state"], "disabled")
        log = self.ok("GET", f"/api/campaigns/{self.campaign_id}/log")
        self.assertEqual([e["action"] for e in log[:2]], ["stream_state", "add"])
        self.assertTrue(log[0]["created_at"].endswith("Z"))
        self.ok("GET", "/api/campaigns/999/log", 404)
        self.ok("POST", "/api/streams/999/state", 404, json={"active": True})

    def test_push_conflict_api(self):
        self.ok("POST", f"/api/streams/{self.sid}/offers", json={"offer_id": 4})
        self.kt.streams[OFFER_STREAM_ID]["offers"][0]["share"] = 50
        r = self.ok("POST", f"/api/streams/{self.sid}/push", 409)
        self.assertIn("Загрузите потоки заново", r["detail"])
        s = self.ok("POST", f"/api/streams/{self.sid}/push", params={"force": "true"})
        self.assertFalse(s["is_dirty"])
        self.assertEqual(self.kt.kt_offers(), {1: 25, 2: 25, 3: 25, 4: 25})

    def test_import_unknown_campaign(self):
        self.ok("POST", "/api/campaigns/import", 404, json={"keitaro_id": 1})

    def test_import_is_idempotent(self):
        again = self.ok("POST", "/api/campaigns/import", json={"keitaro_id": CAMPAIGN_KT_ID})
        self.assertEqual(again["id"], self.campaign_id)


if __name__ == "__main__":
    unittest.main()
