import json
import unittest
from pathlib import Path

import httpx

from app.keitaro import KeitaroClient, KeitaroError

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class KeitaroClientTest(unittest.IsolatedAsyncioTestCase):
    def make_client(self, handler) -> KeitaroClient:
        self.requests: list[httpx.Request] = []

        def recording(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return handler(request)

        client = KeitaroClient("https://kt.example/", "secret", transport=httpx.MockTransport(recording))
        self.addAsyncCleanup(client.aclose)
        return client

    async def test_sends_auth_and_user_agent(self):
        client = self.make_client(lambda r: httpx.Response(200, json=load("offers.json")))
        offers = await client.list_offers()
        request = self.requests[0]
        self.assertEqual(str(request.url), "https://kt.example/admin_api/v1/offers")
        self.assertEqual(request.headers["Api-Key"], "secret")
        self.assertFalse(request.headers["User-Agent"].lower().startswith("python"))
        self.assertEqual(offers[0]["id"], 18813)

    async def test_list_streams_parses_offers_and_filters(self):
        client = self.make_client(lambda r: httpx.Response(200, json=load("streams.json")))
        geo, offers = await client.list_streams(215193)
        self.assertEqual(self.requests[0].url.path, "/admin_api/v1/campaigns/215193/streams")
        self.assertEqual(geo["filters"][0]["name"], "country")
        self.assertEqual(geo["offers"], [])
        self.assertEqual([(o["offer_id"], o["share"]) for o in offers["offers"]], [(18813, 100)])

    async def test_list_campaigns_paginates(self):
        data = [{"id": i} for i in range(5)]

        def handler(request: httpx.Request) -> httpx.Response:
            limit = int(request.url.params["limit"])
            offset = int(request.url.params["offset"])
            return httpx.Response(200, json=data[offset:offset + limit])

        client = self.make_client(handler)
        campaigns = await client.list_campaigns(page_size=2)
        self.assertEqual([c["id"] for c in campaigns], [0, 1, 2, 3, 4])
        self.assertEqual(len(self.requests), 3)

    async def test_update_stream_sends_json(self):
        client = self.make_client(lambda r: httpx.Response(200, json={"id": 7}))
        body = {"offers": [{"offer_id": 1, "share": 60, "state": "active"}]}
        await client.update_stream(7, body)
        request = self.requests[0]
        self.assertEqual(request.method, "PUT")
        self.assertEqual(request.url.path, "/admin_api/v1/streams/7")
        self.assertEqual(json.loads(request.content), body)

    async def test_http_error_raises_keitaro_error(self):
        client = self.make_client(lambda r: httpx.Response(403, json={"title": "Error 1010: Access denied"}))
        with self.assertRaises(KeitaroError) as ctx:
            await client.list_offers()
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("1010", str(ctx.exception))

    async def test_network_error_raises_keitaro_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timeout", request=request)

        client = self.make_client(handler)
        with self.assertRaises(KeitaroError) as ctx:
            await client.list_offers()
        self.assertIsNone(ctx.exception.status)


if __name__ == "__main__":
    unittest.main()
