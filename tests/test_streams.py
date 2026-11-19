import copy
import unittest

from sqlalchemy.pool import StaticPool

from app import streams as svc
from app.db import Base, make_engine, make_sessionmaker
from app.keitaro import KeitaroError
from app.models import Campaign, OfferState

CAMPAIGN_KT_ID = 500
GEO_STREAM_ID = 10
OFFER_STREAM_ID = 11


class FakeKeitaro:
    def __init__(self):
        self.offers = [{"id": i, "name": f"Offer {i}"} for i in (1, 2, 3, 4, 5)]
        self.streams = {
            GEO_STREAM_ID: {
                "id": GEO_STREAM_ID, "name": "Geo", "position": 1, "schema": "redirect",
                "filters": [{"name": "country", "mode": "accept", "payload": ["AU"]}], "offers": [],
            },
            OFFER_STREAM_ID: {
                "id": OFFER_STREAM_ID, "name": "Offers", "position": 2, "schema": "landings", "filters": [],
                "offers": [
                    {"offer_id": 1, "share": 34, "state": "active"},
                    {"offer_id": 2, "share": 33, "state": "active"},
                    {"offer_id": 3, "share": 33, "state": "active"},
                ],
            },
        }
        self.fail_update = False
        self.updates = []

    async def get_campaign(self, campaign_id):
        return {"id": campaign_id, "name": "test_mironov_x", "alias": "x"}

    async def list_streams(self, campaign_id):
        return copy.deepcopy(sorted(self.streams.values(), key=lambda s: s["position"]))

    async def list_offers(self):
        return self.offers

    async def update_stream(self, stream_id, payload):
        if self.fail_update:
            raise KeitaroError("Keitaro HTTP 500: boom", 500)
        self.updates.append((stream_id, payload))
        self.streams[stream_id]["offers"] = [dict(o) for o in payload["offers"]]
        return self.streams[stream_id]

    def kt_offers(self, stream_id=OFFER_STREAM_ID):
        return {o["offer_id"]: o["share"] for o in self.streams[stream_id]["offers"]}


class StreamServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = make_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session = make_sessionmaker(self.engine)()
        self.kt = FakeKeitaro()
        campaign = await svc.import_campaign(self.session, self.kt, CAMPAIGN_KT_ID)
        self.campaign = await svc.fetch_streams(self.session, self.kt, campaign)

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def refetch(self):
        self.campaign = await svc.fetch_streams(self.session, self.kt, self.campaign)

    def stream(self, keitaro_id=OFFER_STREAM_ID):
        return next(s for s in self.campaign.streams if s.keitaro_id == keitaro_id)

    def shares(self, keitaro_id=OFFER_STREAM_ID):
        return {o.offer_id: o.share for o in self.stream(keitaro_id).offers}

    def offer(self, offer_id):
        return svc.find_offer(self.stream(), offer_id)

    async def test_fetch_imports_streams(self):
        geo, offers = self.campaign.streams
        self.assertEqual((geo.name, geo.has_offers, geo.offers), ("Geo", False, []))
        self.assertTrue(offers.has_offers)
        self.assertEqual(self.shares(), {1: 34, 2: 33, 3: 33})
        self.assertEqual(self.offer(2).offer_name, "Offer 2")
        self.assertFalse(offers.is_dirty)

    async def test_add_offer_rebalances_and_marks_dirty(self):
        await svc.add_offer(self.session, self.stream(), 4, "Offer 4")
        self.assertEqual(self.shares(), {1: 25, 2: 25, 3: 25, 4: 25})
        self.assertTrue(self.stream().is_dirty)
        self.assertEqual(self.kt.kt_offers(), {1: 34, 2: 33, 3: 33})

    async def test_push_publishes_and_cleans(self):
        await svc.add_offer(self.session, self.stream(), 4)
        await svc.push(self.session, self.kt, self.stream())
        self.assertEqual(self.kt.kt_offers(), {1: 25, 2: 25, 3: 25, 4: 25})
        self.assertFalse(self.stream().is_dirty)

    async def test_cancel_drops_unpublished_offers(self):
        await svc.add_offer(self.session, self.stream(), 4)
        await svc.add_offer(self.session, self.stream(), 5)
        await svc.cancel(self.session, self.stream())
        self.assertEqual(self.shares(), {1: 34, 2: 33, 3: 33})
        self.assertFalse(self.stream().is_dirty)

    async def test_cancel_restores_removed_offer(self):
        await svc.remove_offer(self.session, self.stream(), self.offer(1))
        await svc.cancel(self.session, self.stream())
        self.assertEqual(self.offer(1).state, OfferState.active)
        self.assertEqual(self.shares(), {1: 34, 2: 33, 3: 33})

    async def test_remove_then_push_keeps_archive(self):
        await svc.remove_offer(self.session, self.stream(), self.offer(1))
        self.assertEqual(self.shares(), {1: 0, 2: 50, 3: 50})
        self.assertTrue(self.stream().is_dirty)
        await svc.push(self.session, self.kt, self.stream())
        self.assertEqual(self.kt.kt_offers(), {2: 50, 3: 50})
        self.assertEqual(self.offer(1).state, OfferState.removed)
        self.assertFalse(self.stream().is_dirty)

    async def test_bring_back_after_push(self):
        await svc.remove_offer(self.session, self.stream(), self.offer(1))
        await svc.push(self.session, self.kt, self.stream())
        await svc.bring_back(self.session, self.stream(), self.offer(1))
        self.assertTrue(self.stream().is_dirty)
        await svc.push(self.session, self.kt, self.stream())
        self.assertEqual(self.kt.kt_offers(), {1: 34, 2: 33, 3: 33})

    async def test_add_of_removed_offer_brings_it_back(self):
        await svc.remove_offer(self.session, self.stream(), self.offer(1))
        await svc.add_offer(self.session, self.stream(), 1)
        self.assertEqual(self.offer(1).state, OfferState.active)
        self.assertEqual(len(self.stream().offers), 3)

    async def test_add_duplicate_fails(self):
        with self.assertRaises(svc.StreamError):
            await svc.add_offer(self.session, self.stream(), 2)

    async def test_remove_unpublished_offer_deletes_it(self):
        await svc.add_offer(self.session, self.stream(), 4)
        await svc.remove_offer(self.session, self.stream(), self.offer(4))
        self.assertEqual(self.shares(), {1: 34, 2: 33, 3: 33})
        self.assertFalse(self.stream().is_dirty)

    async def test_deleted_in_keitaro_becomes_removed(self):
        self.kt.streams[OFFER_STREAM_ID]["offers"] = [
            {"offer_id": 2, "share": 50, "state": "active"},
            {"offer_id": 3, "share": 50, "state": "active"},
        ]
        await self.refetch()
        self.assertEqual(self.offer(1).state, OfferState.removed)
        self.assertEqual(self.shares(), {1: 0, 2: 50, 3: 50})
        self.assertFalse(self.stream().is_dirty)
        await svc.bring_back(self.session, self.stream(), self.offer(1))
        await svc.push(self.session, self.kt, self.stream())
        self.assertEqual(self.kt.kt_offers(), {1: 34, 2: 33, 3: 33})

    async def test_added_in_keitaro_appears_with_its_share(self):
        self.kt.streams[OFFER_STREAM_ID]["offers"].append({"offer_id": 5, "share": 10, "state": "active"})
        await self.refetch()
        self.assertEqual(self.shares()[5], 10)

    async def test_fetch_resets_unpublished_changes(self):
        await svc.add_offer(self.session, self.stream(), 4)
        await svc.remove_offer(self.session, self.stream(), self.offer(1))
        await self.refetch()
        self.assertEqual(self.shares(), {1: 34, 2: 33, 3: 33})
        self.assertFalse(self.stream().is_dirty)

    async def test_pin_survives_add_and_remove(self):
        await svc.add_offer(self.session, self.stream(), 4)
        await svc.set_pin(self.session, self.stream(), self.offer(1), True)
        await svc.remove_offer(self.session, self.stream(), self.offer(4))
        self.assertEqual(self.shares(), {1: 25, 2: 38, 3: 37})
        await svc.add_offer(self.session, self.stream(), 5)
        self.assertEqual(self.shares(), {1: 25, 2: 25, 3: 25, 5: 25})

    async def test_pin_with_value(self):
        await svc.set_pin(self.session, self.stream(), self.offer(1), True, 50)
        self.assertEqual(self.shares(), {1: 50, 2: 25, 3: 25})

    async def test_pin_persists_after_fetch(self):
        await svc.set_pin(self.session, self.stream(), self.offer(1), True, 50)
        await svc.push(self.session, self.kt, self.stream())
        await self.refetch()
        self.assertTrue(self.offer(1).pinned)

    async def test_invalid_pin_reverts(self):
        await svc.set_pin(self.session, self.stream(), self.offer(1), True, 60)
        with self.assertRaises(svc.StreamError):
            await svc.set_pin(self.session, self.stream(), self.offer(2), True, 50)
        self.assertFalse(self.offer(2).pinned)
        self.assertEqual(self.shares(), {1: 60, 2: 20, 3: 20})

    async def test_removing_last_free_offer_with_partial_pins_fails(self):
        await svc.set_pin(self.session, self.stream(), self.offer(1), True, 40)
        await svc.set_pin(self.session, self.stream(), self.offer(2), True, 30)
        with self.assertRaises(svc.StreamError):
            await svc.remove_offer(self.session, self.stream(), self.offer(3))
        self.assertEqual(self.offer(3).state, OfferState.active)
        self.assertEqual(self.shares(), {1: 40, 2: 30, 3: 30})

    async def test_push_error_keeps_stream_dirty(self):
        await svc.add_offer(self.session, self.stream(), 4)
        self.kt.fail_update = True
        with self.assertRaises(svc.StreamError):
            await svc.push(self.session, self.kt, self.stream())
        self.assertTrue(self.stream().is_dirty)
        self.assertIn("boom", self.stream().last_error)

    async def test_push_without_active_offers_fails(self):
        for offer_id in (1, 2, 3):
            await svc.remove_offer(self.session, self.stream(), self.offer(offer_id))
        with self.assertRaises(svc.StreamError):
            await svc.push(self.session, self.kt, self.stream())
        self.assertEqual(self.kt.updates, [])

    async def test_stream_deleted_in_keitaro_disappears(self):
        del self.kt.streams[GEO_STREAM_ID]
        await self.refetch()
        self.assertEqual([s.keitaro_id for s in self.campaign.streams], [OFFER_STREAM_ID])

    async def test_cannot_add_offer_to_redirect_stream(self):
        with self.assertRaises(svc.StreamError):
            await svc.add_offer(self.session, self.stream(GEO_STREAM_ID), 4)

    async def test_import_is_idempotent(self):
        again = await svc.import_campaign(self.session, self.kt, CAMPAIGN_KT_ID)
        self.assertEqual(again.id, self.campaign.id)
        self.assertIsInstance(again, Campaign)


if __name__ == "__main__":
    unittest.main()
