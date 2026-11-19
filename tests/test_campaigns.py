import unittest

from sqlalchemy.pool import StaticPool

from app import campaigns
from app.db import Base, make_engine, make_sessionmaker
from app.errors import AppError
from app.keitaro import KeitaroError
from app.offers import OfferCatalog
from tests.helpers import SETTINGS, ApiCase


class FakeKeitaro:
    def __init__(self, fail_stream_n: int | None = None, fail_delete: bool = False):
        self.campaigns: dict[int, dict] = {}
        self.streams: list[dict] = []
        self.deleted: list[int] = []
        self.offer_calls = 0
        self.fail_stream_n = fail_stream_n
        self.fail_delete = fail_delete

    async def list_offers(self):
        self.offer_calls += 1
        return [
            {"id": 18813, "name": "18813 Flexacil PE", "state": "active"},
            {"id": 200, "name": "Miaflow", "state": "active"},
            {"id": 300, "name": "Old offer", "state": "archived"},
        ]

    async def create_campaign(self, payload):
        campaign = {"id": 900 + len(self.campaigns), **payload}
        self.campaigns[campaign["id"]] = campaign
        return campaign

    async def get_campaign(self, campaign_id):
        return self.campaigns[campaign_id]

    async def delete_campaign(self, campaign_id):
        if self.fail_delete:
            raise KeitaroError("Keitaro HTTP 500: nope", 500)
        self.deleted.append(campaign_id)

    async def create_stream(self, payload):
        if self.fail_stream_n is not None and len(self.streams) + 1 == self.fail_stream_n:
            raise KeitaroError("Keitaro HTTP 422: bad stream", 422)
        stream = {"id": 5000 + len(self.streams), "offers": [], **payload}
        self.streams.append(stream)
        return stream

    async def list_streams(self, campaign_id):
        return [s for s in self.streams if s["campaign_id"] == campaign_id]


class DbCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = make_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session = make_sessionmaker(self.engine)()

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()


class CreateCampaignTest(DbCase):
    async def create(self, kt, name="campaign1", geo="au", offer_id=18813):
        return await campaigns.create_campaign(
            self.session, kt, OfferCatalog(kt), SETTINGS, name, geo, offer_id
        )

    async def test_creates_campaign_with_two_streams(self):
        kt = FakeKeitaro()
        campaign = await self.create(kt)

        sent = kt.campaigns[campaign.keitaro_id]
        self.assertEqual(sent["name"], "test_mironov_campaign1")
        self.assertTrue(sent["alias"].startswith("test-mironov-campaign1-"))
        self.assertEqual(
            {k: sent[k] for k in ("type", "cost_type", "cost_value", "cost_currency", "cost_auto")},
            {"type": "position", "cost_type": "CPC", "cost_value": 0, "cost_currency": "USD", "cost_auto": True},
        )
        self.assertEqual((sent["domain_id"], sent["group_id"], sent["traffic_source_id"]), (1, 2, 3))

        geo, offers = kt.streams
        self.assertEqual((geo["position"], geo["schema"], geo["action_payload"]), (1, "redirect", "https://google.com"))
        self.assertEqual(geo["filters"], [{"name": "country", "mode": "accept", "payload": ["AU"]}])
        self.assertEqual((offers["position"], offers["schema"]), (2, "landings"))
        self.assertEqual(offers["offers"], [{"offer_id": 18813, "share": 100, "state": "active"}])

        self.assertEqual(campaign.geo, "AU")
        self.assertEqual([s.has_offers for s in campaign.streams], [False, True])
        self.assertEqual(campaign.streams[1].offers[0].offer_name, "18813 Flexacil PE")

    async def test_prefix_not_duplicated(self):
        kt = FakeKeitaro()
        campaign = await self.create(kt, name="test_mironov_x")
        self.assertEqual(campaign.name, "test_mironov_x")

    async def test_invalid_geo(self):
        kt = FakeKeitaro()
        for geo in ("AUS", "1A", ""):
            with self.assertRaises(AppError):
                await self.create(kt, geo=geo)
        self.assertEqual(kt.campaigns, {})

    async def test_unknown_offer(self):
        kt = FakeKeitaro()
        with self.assertRaises(AppError):
            await self.create(kt, offer_id=1)
        self.assertEqual(kt.campaigns, {})

    async def test_stream_failure_deletes_campaign(self):
        kt = FakeKeitaro(fail_stream_n=2)
        with self.assertRaises(AppError) as ctx:
            await self.create(kt)
        self.assertEqual(kt.deleted, [900])
        self.assertIn("удалена", str(ctx.exception))

    async def test_failed_rollback_is_reported(self):
        kt = FakeKeitaro(fail_stream_n=1, fail_delete=True)
        with self.assertRaises(AppError) as ctx:
            await self.create(kt)
        self.assertIn("осталась в Keitaro", str(ctx.exception))


class OfferCatalogTest(unittest.IsolatedAsyncioTestCase):
    async def test_search_by_name_and_id(self):
        catalog = OfferCatalog(FakeKeitaro())
        self.assertEqual([o["id"] for o in await catalog.search("mia")], [200])
        self.assertEqual([o["id"] for o in await catalog.search("188")], [18813])
        self.assertEqual([o["id"] for o in await catalog.search("")], [18813, 200])

    async def test_inactive_offers_hidden(self):
        catalog = OfferCatalog(FakeKeitaro())
        self.assertEqual(await catalog.search("old"), [])

    async def test_cached(self):
        kt = FakeKeitaro()
        catalog = OfferCatalog(kt)
        await catalog.search("a")
        await catalog.search("b")
        self.assertEqual(kt.offer_calls, 1)


class CampaignApiTest(ApiCase):
    def make_keitaro(self):
        return FakeKeitaro()

    def test_create_and_errors(self):
        body = self.ok("POST", "/api/campaigns", 201, json={"name": "c1", "geo": "mx", "offer_id": 18813})
        self.assertEqual((body["name"], body["geo"], len(body["streams"])), ("test_mironov_c1", "MX", 2))
        self.assertEqual(body["streams"][1]["offers"][0]["share"], 100)

        self.ok("POST", "/api/campaigns", 400, json={"name": "c1", "geo": "m1", "offer_id": 18813})
        self.ok("POST", "/api/campaigns", 422, json={"name": "c1", "geo": "MX"})

        offers = self.ok("GET", "/api/offers", params={"q": "flex"})
        self.assertEqual(offers, [{"id": 18813, "name": "18813 Flexacil PE"}])
        self.assertEqual(len(self.ok("GET", "/api/campaigns")), 1)


if __name__ == "__main__":
    unittest.main()
