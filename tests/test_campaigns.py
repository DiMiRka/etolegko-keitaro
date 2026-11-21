import unittest

from sqlalchemy.pool import StaticPool

from app import campaigns
from app.db import Base, make_engine, make_sessionmaker
from app.errors import AppError
from app.keitaro import KeitaroError
from app.offers import OfferCatalog
from app.references import References
from tests.helpers import SETTINGS, ApiCase


class FakeKeitaro:
    def __init__(self, fail_stream_n: int | None = None, fail_delete: bool = False):
        self.campaigns: dict[int, dict] = {}
        self.streams: list[dict] = []
        self.deleted: list[int] = []
        self.offer_calls = 0
        self.reference_calls = 0
        self.state_calls = []
        self.groups = [{"id": 2, "name": "FORTESTS"}, {"id": 7, "name": "alpha"}]
        self.groups_forbidden = False
        self.reports = []
        self.fail_stream_n = fail_stream_n
        self.fail_delete = fail_delete

    async def list_offers(self):
        self.offer_calls += 1
        return [
            {"id": 18813, "name": "18813 Flexacil PE", "state": "active"},
            {"id": 200, "name": "Miaflow", "state": "active"},
            {"id": 300, "name": "Old offer", "state": "archived"},
        ]

    async def list_domains(self):
        self.reference_calls += 1
        return [
            {"id": 1, "name": "kylovoa.com", "state": "active"},
            {"id": 5, "name": "other.com", "state": "active"},
            {"id": 6, "name": "old.com", "state": "deleted"},
        ]

    async def list_campaign_groups(self):
        return list(self.groups)

    async def create_campaign_group(self, name):
        if self.groups_forbidden:
            raise KeitaroError("Keitaro HTTP 403: You have no permission to access this page - Groups", 403)
        group = {"id": 100 + len(self.groups), "name": name, "type": "campaigns"}
        self.groups.append(group)
        return group

    async def list_traffic_sources(self):
        return [{"id": 3, "name": "FORTESTS", "state": "active"}]

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
        stream["filters"] = [{"id": 70 + i, **f} for i, f in enumerate(payload.get("filters", []))]
        self.streams.append(stream)
        return stream

    async def list_streams(self, campaign_id):
        return [s for s in self.streams if s["campaign_id"] == campaign_id]

    async def enable_campaign(self, campaign_id):
        self.state_calls.append((campaign_id, True))
        self.campaigns[campaign_id]["state"] = "active"
        return [self.campaigns[campaign_id]]

    async def disable_campaign(self, campaign_id):
        self.state_calls.append((campaign_id, False))
        self.campaigns[campaign_id]["state"] = "disabled"
        return [self.campaigns[campaign_id]]

    async def build_report(self, body):
        self.reports.append(body)
        ids = body["filters"][0]["expression"]
        return {"rows": [{"campaign_id": ids[0], "clicks": 9, "conversions": 1}]}

    async def update_campaign(self, campaign_id, payload):
        self.campaigns[campaign_id].update(payload)
        return self.campaigns[campaign_id]

    async def update_stream(self, stream_id, payload):
        stream = next(s for s in self.streams if s["id"] == stream_id)
        stream.update(payload)
        return stream


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
        self.assertEqual(geo["filters"], [{"id": 70, "name": "country", "mode": "accept", "payload": ["AU"]}])
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


class UpdateCampaignTest(DbCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.kt = FakeKeitaro()
        self.campaign = await campaigns.create_campaign(
            self.session, self.kt, OfferCatalog(self.kt), SETTINGS, "c1", "AU", 18813
        )

    async def update(self, **kwargs):
        return await campaigns.update_campaign(self.session, self.kt, SETTINGS, self.campaign, **kwargs)

    async def test_rename_adds_prefix(self):
        c = await self.update(name="renamed")
        self.assertEqual(c.name, "test_mironov_renamed")
        self.assertEqual(self.kt.campaigns[c.keitaro_id]["name"], "test_mironov_renamed")

    async def test_change_geo_updates_filter_in_place(self):
        c = await self.update(geo="mx")
        geo_stream = self.kt.streams[0]
        self.assertEqual(geo_stream["filters"], [{"id": 70, "name": "country", "mode": "accept", "payload": ["MX"]}])
        self.assertEqual(geo_stream["name"], "MX -> Google")
        self.assertEqual(c.geo, "MX")
        self.assertEqual(c.streams[0].name, "MX -> Google")

    async def test_custom_stream_name_is_kept(self):
        self.kt.streams[0]["name"] = "Australia"
        await self.update(geo="RO")
        self.assertEqual(self.kt.streams[0]["name"], "Australia")

    async def test_same_values_do_nothing(self):
        self.kt.update_campaign = self.kt.update_stream = None
        c = await self.update(name="test_mironov_c1", geo="au")
        self.assertEqual((c.name, c.geo), ("test_mironov_c1", "AU"))

    async def test_geo_without_country_stream_fails(self):
        self.kt.streams[0]["filters"] = []
        with self.assertRaises(AppError):
            await self.update(geo="MX")

    async def test_invalid_geo(self):
        with self.assertRaises(AppError):
            await self.update(geo="M1")

    async def test_create_stores_tracking(self):
        c = self.campaign
        self.assertEqual((c.domain_id, c.group_id, c.traffic_source_id), (1, 2, 3))

    async def test_change_tracking_in_one_request(self):
        calls = []
        original = self.kt.update_campaign

        async def spy(campaign_id, payload):
            calls.append(payload)
            return await original(campaign_id, payload)

        self.kt.update_campaign = spy
        c = await self.update(name="renamed", domain_id=5, group_id=7, traffic_source_id=3)
        self.assertEqual(calls, [{"name": "test_mironov_renamed", "domain_id": 5, "group_id": 7}])
        self.assertEqual((c.domain_id, c.group_id, c.traffic_source_id), (5, 7, 3))

    async def test_fetch_reads_tracking(self):
        self.kt.campaigns[self.campaign.keitaro_id].update(domain_id=5, group_id=7)
        c = await campaigns.fetch_streams(self.session, self.kt, self.campaign)
        self.assertEqual((c.domain_id, c.group_id), (5, 7))

    async def test_fetch_reads_state_and_url(self):
        self.kt.campaigns[self.campaign.keitaro_id].update(state="active", domain="https://kylovoa.com/")
        c = await campaigns.fetch_streams(self.session, self.kt, self.campaign)
        self.assertEqual(c.state, "active")
        self.assertEqual(c.url, "https://kylovoa.com/" + c.alias)

    async def test_set_state(self):
        c = await campaigns.set_state(self.session, self.kt, self.campaign, False)
        self.assertEqual((c.state, self.kt.state_calls), ("disabled", [(c.keitaro_id, False)]))
        c = await campaigns.set_state(self.session, self.kt, self.campaign, True)
        self.assertEqual(c.state, "active")

    async def test_settings_roundtrip(self):
        self.kt.campaigns[self.campaign.keitaro_id].update(
            uniqueness_method="ip", uniqueness_param=None, uniqueness_use_cookies=True,
            cookies_ttl=24, traffic_loss=0, notes=None,
        )
        s = await campaigns.campaign_settings(self.kt, self.campaign)
        self.assertEqual((s["type"], s["cost_type"], s["notes"], s["uniqueness_param"]), ("position", "CPC", "", ""))

        calls = []
        original = self.kt.update_campaign

        async def spy(campaign_id, payload):
            calls.append(payload)
            return await original(campaign_id, payload)

        self.kt.update_campaign = spy
        s = await campaigns.update_settings(self.session, self.kt, self.campaign, {
            "cost_value": 0.0, "cost_type": "CPM", "notes": "hello", "cookies_ttl": 48,
        })
        self.assertEqual(calls, [{"cost_type": "CPM", "notes": "hello", "cookies_ttl": 48}])
        self.assertEqual((s["cost_type"], s["notes"], s["cookies_ttl"]), ("CPM", "hello", 48))

        await campaigns.update_settings(self.session, self.kt, self.campaign, {"cost_type": "CPM"})
        self.assertEqual(len(calls), 1)

    async def test_param_uniqueness_requires_name(self):
        self.kt.campaigns[self.campaign.keitaro_id].update(uniqueness_method="ip", uniqueness_param="")
        with self.assertRaises(AppError):
            await campaigns.update_settings(self.session, self.kt, self.campaign, {"uniqueness_method": "param"})
        s = await campaigns.update_settings(
            self.session, self.kt, self.campaign, {"uniqueness_method": "param", "uniqueness_param": "sub_id"}
        )
        self.assertEqual((s["uniqueness_method"], s["uniqueness_param"]), ("param", "sub_id"))

    async def test_fetch_derives_geo(self):
        self.campaign.geo = None
        await self.session.commit()
        c = await campaigns.fetch_streams(self.session, self.kt, self.campaign)
        self.assertEqual(c.geo, "AU")


class ReferencesTest(unittest.IsolatedAsyncioTestCase):
    async def test_active_only_and_sorted_groups(self):
        refs = await References(FakeKeitaro()).all()
        self.assertEqual([d["id"] for d in refs["domains"]], [1, 5])
        self.assertEqual([g["name"] for g in refs["groups"]], ["alpha", "FORTESTS"])
        self.assertEqual(refs["traffic_sources"], [{"id": 3, "name": "FORTESTS"}])

    async def test_check(self):
        refs = References(FakeKeitaro())
        await refs.check(5, 7, 3)
        for ids in ((6, 2, 3), (1, 99, 3), (1, 2, 99)):
            with self.assertRaises(AppError):
                await refs.check(*ids)

    async def test_cached(self):
        kt = FakeKeitaro()
        refs = References(kt)
        await refs.all()
        await refs.check(1, 2, 3)
        self.assertEqual(kt.reference_calls, 1)

    async def test_create_group_refreshes_cache(self):
        refs = References(FakeKeitaro())
        await refs.all()
        g = await refs.create_group("  test_mironov_g1 ")
        self.assertEqual(g["name"], "test_mironov_g1")
        self.assertIn(g["id"], [x["id"] for x in (await refs.all())["groups"]])
        await refs.check(group_id=g["id"])

    async def test_create_group_rejects_duplicates(self):
        refs = References(FakeKeitaro())
        with self.assertRaises(AppError) as ctx:
            await refs.create_group("FORTESTS")
        self.assertIn("#2", str(ctx.exception))
        with self.assertRaises(AppError):
            await refs.create_group("   ")


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

        updated = self.ok("PATCH", f"/api/campaigns/{body['id']}", json={"name": "c2", "geo": "ro"})
        self.assertEqual((updated["name"], updated["geo"]), ("test_mironov_c2", "RO"))
        self.ok("PATCH", f"/api/campaigns/{body['id']}", 400, json={"geo": "R1"})
        self.ok("PATCH", "/api/campaigns/999", 404, json={"geo": "RO"})

        moved = self.ok("PATCH", f"/api/campaigns/{body['id']}", json={"group_id": 7, "domain_id": 5})
        self.assertEqual((moved["group_id"], moved["domain_id"], moved["traffic_source_id"]), (7, 5, 3))
        r = self.ok("PATCH", f"/api/campaigns/{body['id']}", 400, json={"group_id": 99})
        self.assertIn("Группа 99", r["detail"])
        self.assertEqual(self.kt.campaigns[body["keitaro_id"]]["group_id"], 7)

    def test_state_and_list_stats(self):
        created = self.ok("POST", "/api/campaigns", 201, json={"name": "s1", "geo": "AU", "offer_id": 18813})
        off = self.ok("POST", f"/api/campaigns/{created['id']}/state", json={"active": False})
        self.assertEqual(off["state"], "disabled")
        listed = self.ok("GET", "/api/campaigns")[0]
        self.assertEqual((listed["state"], listed["group_id"]), ("disabled", 2))
        stats = self.ok("GET", "/api/campaigns/stats")
        self.assertEqual(stats["campaigns"][str(created["keitaro_id"])]["clicks"], 9)
        self.assertEqual(self.kt.reports[-1]["filters"][0]["operator"], "IN_LIST")
        self.ok("POST", "/api/campaigns/999/state", 404, json={"active": True})

    def test_settings_api(self):
        created = self.ok("POST", "/api/campaigns", 201, json={"name": "st", "geo": "AU", "offer_id": 18813})
        url = f"/api/campaigns/{created['id']}/settings"
        self.assertEqual(self.ok("GET", url)["cost_currency"], "USD")
        s = self.ok("PATCH", url, json={"cost_currency": "EUR", "traffic_loss": 5})
        self.assertEqual((s["cost_currency"], s["traffic_loss"]), ("EUR", 5))
        self.ok("PATCH", url, 422, json={"cost_type": "CPA"})
        self.ok("PATCH", url, 422, json={"traffic_loss": 100})
        self.ok("PATCH", url, 422, json={"cookies_ttl": 0})
        log = self.ok("GET", f"/api/campaigns/{created['id']}/log")
        self.assertEqual(log[0]["action"], "settings")
        self.assertIn("валюта: USD → EUR", log[0]["message"])
        self.ok("GET", "/api/campaigns/999/settings", 404)

    def test_create_group_api(self):
        g = self.ok("POST", "/api/groups", 201, json={"name": "mx"})
        self.assertEqual(g["name"], "test_mironov_mx")
        self.ok("POST", "/api/groups", 400, json={"name": "test_mironov_mx"})
        self.ok("POST", "/api/groups", 422, json={"name": ""})
        created = self.ok("POST", "/api/campaigns", 201, json={
            "name": "grp", "geo": "AU", "offer_id": 18813, "group_id": g["id"],
        })
        self.assertEqual(self.kt.campaigns[created["keitaro_id"]]["group_id"], g["id"])

    def test_create_group_forbidden(self):
        self.kt.groups_forbidden = True
        r = self.ok("POST", "/api/groups", 502, json={"name": "nope"})
        self.assertIn("403", r["detail"])

    def test_list_stats_without_campaigns(self):
        self.assertEqual(self.ok("GET", "/api/campaigns/stats")["campaigns"], {})
        self.assertEqual(self.kt.reports, [])

    def test_references_endpoint(self):
        refs = self.ok("GET", "/api/references")
        self.assertEqual(refs["defaults"], {"domain_id": 1, "group_id": 2, "traffic_source_id": 3})
        self.assertEqual([d["name"] for d in refs["domains"]], ["kylovoa.com", "other.com"])

    def test_create_with_chosen_tracking(self):
        body = {"name": "c3", "geo": "AU", "offer_id": 18813, "domain_id": 5, "group_id": 7}
        created = self.ok("POST", "/api/campaigns", 201, json=body)
        sent = self.kt.campaigns[created["keitaro_id"]]
        self.assertEqual((sent["domain_id"], sent["group_id"], sent["traffic_source_id"]), (5, 7, 3))

    def test_create_with_unknown_domain_fails_before_keitaro(self):
        r = self.ok("POST", "/api/campaigns", 400, json={"name": "c4", "geo": "AU", "offer_id": 18813, "domain_id": 6})
        self.assertIn("Домен 6", r["detail"])
        self.assertEqual(self.kt.campaigns, {})


if __name__ == "__main__":
    unittest.main()
