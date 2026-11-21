import copy
import unittest

from sqlalchemy.pool import StaticPool

from app import audit
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
        self.campaign_gone = False
        self.updates = []

    async def get_campaign(self, campaign_id):
        if self.campaign_gone:
            raise KeitaroError("Keitaro HTTP 404: not found", 404)
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

    async def get_stream(self, stream_id):
        return copy.deepcopy(self.streams[stream_id])

    async def enable_stream(self, stream_id):
        self.streams[stream_id]["state"] = "active"
        return [self.streams[stream_id]]

    async def disable_stream(self, stream_id):
        self.streams[stream_id]["state"] = "disabled"
        return [self.streams[stream_id]]

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

    async def test_fetch_of_campaign_gone_from_keitaro(self):
        self.kt.campaign_gone = True
        with self.assertRaises(svc.StreamError) as ctx:
            await self.refetch()
        self.assertIn("больше нет в Keitaro", str(ctx.exception))

    async def test_disabled_offer_is_kept_as_is(self):
        self.kt.streams[OFFER_STREAM_ID]["offers"] = [
            {"offer_id": 1, "share": 50, "state": "active"},
            {"offer_id": 2, "share": 50, "state": "active"},
            {"offer_id": 3, "share": 20, "state": "disabled"},
        ]
        await self.refetch()
        self.assertTrue(self.offer(3).disabled)
        self.assertFalse(self.stream().is_dirty)

        await svc.add_offer(self.session, self.stream(), 4)
        self.assertEqual(self.shares(), {1: 34, 2: 33, 3: 20, 4: 33})
        with self.assertRaises(svc.StreamError):
            await svc.set_pin(self.session, self.stream(), self.offer(3), True)

        await svc.push(self.session, self.kt, self.stream())
        sent = {o["offer_id"]: (o["share"], o["state"]) for o in self.kt.updates[-1][1]["offers"]}
        self.assertEqual(sent, {1: (34, "active"), 2: (33, "active"), 3: (20, "disabled"), 4: (33, "active")})

    async def test_removing_disabled_offer_drops_it_on_push(self):
        self.kt.streams[OFFER_STREAM_ID]["offers"][2]["state"] = "disabled"
        await self.refetch()
        await svc.remove_offer(self.session, self.stream(), self.offer(3))
        self.assertEqual(self.shares(), {1: 50, 2: 50, 3: 0})
        await svc.push(self.session, self.kt, self.stream())
        self.assertEqual(self.kt.kt_offers(), {1: 50, 2: 50})

    async def test_empty_landings_stream_accepts_offers(self):
        self.kt.streams[12] = {"id": 12, "name": "Empty", "position": 3, "schema": "landings", "offers": []}
        await self.refetch()
        empty = self.stream(12)
        self.assertTrue(empty.has_offers)
        await svc.add_offer(self.session, empty, 5)
        self.assertEqual(self.shares(12), {5: 100})

    async def test_failed_remove_keeps_order(self):
        await svc.add_offer(self.session, self.stream(), 4)
        await svc.set_pin(self.session, self.stream(), self.offer(1), True, 40)
        await svc.set_pin(self.session, self.stream(), self.offer(2), True, 30)
        await svc.set_pin(self.session, self.stream(), self.offer(3), True, 20)
        with self.assertRaises(svc.StreamError):
            await svc.remove_offer(self.session, self.stream(), self.offer(4))
        self.assertEqual([o.offer_id for o in self.stream().offers], [1, 2, 3, 4])

    async def test_forget_campaign(self):
        await svc.forget_campaign(self.session, self.campaign)
        with self.assertRaises(svc.NotFound):
            await svc.load_campaign(self.session, self.campaign.id)

    async def log(self):
        return list(reversed(await audit.history(self.session, self.campaign.id)))

    async def test_journal_records_cycle(self):
        await svc.add_offer(self.session, self.stream(), 4, "Offer 4")
        await svc.push(self.session, self.kt, self.stream())
        await svc.remove_offer(self.session, self.stream(), self.offer(4))
        await svc.cancel(self.session, self.stream())
        await svc.set_pin(self.session, self.stream(), self.offer(1), True, 40)
        entries = await self.log()
        self.assertEqual(
            [e["action"] for e in entries], ["import", "fetch", "add", "push", "remove", "cancel", "pin"]
        )
        add, push = entries[2], entries[3]
        self.assertIn("добавлен оффер 4 Offer 4", add["message"])
        self.assertEqual(add["details"]["before"], {"1": 34, "2": 33, "3": 33})
        self.assertEqual(add["details"]["after"], {"1": 25, "2": 25, "3": 25, "4": 25})
        self.assertEqual(push["details"]["before"], {"1": 34, "2": 33, "3": 33})
        self.assertEqual(entries[-1]["message"], "Поток «Offers»: закреплена доля 40% у оффера 1 Offer 1")

    async def test_cancel_without_changes_not_logged(self):
        await svc.cancel(self.session, self.stream())
        self.assertNotIn("cancel", [e["action"] for e in await self.log()])

    async def test_failed_push_logged(self):
        await svc.add_offer(self.session, self.stream(), 4)
        self.kt.fail_update = True
        with self.assertRaises(svc.StreamError):
            await svc.push(self.session, self.kt, self.stream())
        last = (await self.log())[-1]
        self.assertEqual(last["action"], "push_failed")
        self.assertIn("boom", last["message"])

    async def test_sync_logs_deleted_in_keitaro(self):
        await svc.add_offer(self.session, self.stream(), 5)
        self.kt.streams[OFFER_STREAM_ID]["offers"].pop(0)
        await self.refetch()
        sync = [e for e in await self.log() if e["action"] == "sync"]
        self.assertEqual(len(sync), 1)
        self.assertIn("удалены в Keitaro: 1", sync[0]["message"])
        self.assertIn("сброшены неопубликованные изменения: 1, 2, 3, 5", sync[0]["message"])
        self.assertEqual(sync[0]["details"]["removed_in_kt"], [1])

    async def test_stream_state(self):
        self.assertIsNone(self.stream(GEO_STREAM_ID).state)
        self.kt.streams[GEO_STREAM_ID]["state"] = "active"
        await self.refetch()
        geo = self.stream(GEO_STREAM_ID)
        self.assertEqual(geo.state, "active")
        await svc.set_stream_state(self.session, self.kt, geo, False)
        self.assertEqual((geo.state, self.kt.streams[GEO_STREAM_ID]["state"]), ("disabled", "disabled"))
        await svc.set_stream_state(self.session, self.kt, geo, True)
        self.assertEqual(geo.state, "active")
        self.assertEqual(
            [e["message"] for e in await self.log() if e["action"] == "stream_state"],
            ["Поток «Geo»: выключен", "Поток «Geo»: включён"],
        )

    async def test_push_refuses_when_keitaro_changed(self):
        await svc.add_offer(self.session, self.stream(), 4)
        self.kt.streams[OFFER_STREAM_ID]["offers"][0]["share"] = 50
        self.kt.streams[OFFER_STREAM_ID]["offers"].pop(1)
        self.kt.streams[OFFER_STREAM_ID]["offers"].append({"offer_id": 5, "share": 17, "state": "active"})
        with self.assertRaises(svc.Conflict) as ctx:
            await svc.push(self.session, self.kt, self.stream())
        message = str(ctx.exception)
        self.assertIn("у оффера 1 доля 34% → 50%", message)
        self.assertIn("оффер 2 удалён в Keitaro", message)
        self.assertIn("оффер 5 добавлен в Keitaro (17%)", message)
        self.assertEqual(self.kt.updates, [])
        self.assertTrue(self.stream().is_dirty)
        self.assertIn("изменён в Keitaro", self.stream().last_error)
        self.assertEqual((await self.log())[-1]["action"], "push_conflict")

    async def test_force_push_overwrites(self):
        await svc.add_offer(self.session, self.stream(), 4)
        self.kt.streams[OFFER_STREAM_ID]["offers"][0]["share"] = 50
        await svc.push(self.session, self.kt, self.stream(), force=True)
        self.assertEqual(self.kt.kt_offers(), {1: 25, 2: 25, 3: 25, 4: 25})
        last = (await self.log())[-1]
        self.assertIn("с перезаписью", last["message"])

    async def test_disabled_in_keitaro_is_conflict(self):
        await svc.add_offer(self.session, self.stream(), 4)
        self.kt.streams[OFFER_STREAM_ID]["offers"][2]["state"] = "disabled"
        with self.assertRaises(svc.Conflict) as ctx:
            await svc.push(self.session, self.kt, self.stream())
        self.assertIn("оффер 3 отключён в Keitaro", str(ctx.exception))

    async def test_no_conflict_after_refetch(self):
        self.kt.streams[OFFER_STREAM_ID]["offers"][0]["share"] = 50
        self.kt.streams[OFFER_STREAM_ID]["offers"][1]["share"] = 25
        self.kt.streams[OFFER_STREAM_ID]["offers"][2]["share"] = 25
        await self.refetch()
        await svc.add_offer(self.session, self.stream(), 4)
        await svc.push(self.session, self.kt, self.stream())
        self.assertEqual(sum(self.kt.kt_offers().values()), 100)

    async def test_forget_campaign_drops_journal(self):
        await svc.forget_campaign(self.session, self.campaign)
        self.assertEqual(await audit.history(self.session, self.campaign.id), [])

    async def test_import_is_idempotent(self):
        again = await svc.import_campaign(self.session, self.kt, CAMPAIGN_KT_ID)
        self.assertEqual(again.id, self.campaign.id)
        self.assertIsInstance(again, Campaign)


if __name__ == "__main__":
    unittest.main()
