from typing import Any

import httpx


class KeitaroError(Exception):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def _error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return f"Keitaro HTTP {response.status_code}: {response.text[:200]}"
    if isinstance(data, dict):
        for key in ("error", "message", "detail", "title"):
            if data.get(key):
                return f"Keitaro HTTP {response.status_code}: {data[key]}"
    return f"Keitaro HTTP {response.status_code}: {str(data)[:200]}"


class KeitaroClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        user_agent: str = "etolegko-keitaro-wrapper/0.1",
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/admin_api/v1",
            headers={"Api-Key": api_key, "Accept": "application/json", "User-Agent": user_agent},
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "KeitaroClient":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> Any:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            raise KeitaroError(f"Keitaro unavailable: {e.__class__.__name__}") from e
        if response.is_error:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            raise KeitaroError(_error_message(response), response.status_code, payload)
        if not response.content:
            return None
        return response.json()

    async def list_campaigns(self, page_size: int = 100) -> list[dict]:
        result: list[dict] = []
        offset = 0
        while True:
            page = await self._request("GET", "/campaigns", params={"limit": page_size, "offset": offset})
            result.extend(page)
            if len(page) < page_size:
                return result
            offset += page_size

    async def get_campaign(self, campaign_id: int) -> dict:
        return await self._request("GET", f"/campaigns/{campaign_id}")

    async def create_campaign(self, payload: dict) -> dict:
        return await self._request("POST", "/campaigns", json=payload)

    async def update_campaign(self, campaign_id: int, payload: dict) -> dict:
        return await self._request("PUT", f"/campaigns/{campaign_id}", json=payload)

    async def delete_campaign(self, campaign_id: int) -> None:
        await self._request("DELETE", f"/campaigns/{campaign_id}")

    async def list_streams(self, campaign_id: int) -> list[dict]:
        return await self._request("GET", f"/campaigns/{campaign_id}/streams")

    async def get_stream(self, stream_id: int) -> dict:
        return await self._request("GET", f"/streams/{stream_id}")

    async def create_stream(self, payload: dict) -> dict:
        return await self._request("POST", "/streams", json=payload)

    async def update_stream(self, stream_id: int, payload: dict) -> dict:
        return await self._request("PUT", f"/streams/{stream_id}", json=payload)

    async def build_report(self, payload: dict) -> dict:
        return await self._request("POST", "/report/build", json=payload)

    async def list_offers(self) -> list[dict]:
        return await self._request("GET", "/offers")

    async def list_domains(self) -> list[dict]:
        return await self._request("GET", "/domains")

    async def list_campaign_groups(self) -> list[dict]:
        return await self._request("GET", "/groups", params={"type": "campaigns"})

    async def list_traffic_sources(self) -> list[dict]:
        return await self._request("GET", "/traffic_sources")
