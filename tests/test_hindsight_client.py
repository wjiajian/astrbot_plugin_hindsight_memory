import json
import unittest

import httpx

from hindsight_client import HindsightClient, HindsightClientError


class HindsightClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_recall_request_body_uses_strict_scope_tags(self):
        seen = {}

        async def handler(request):
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"results": []})

        client = _client_with_transport(handler)

        await client.recall("bank", "hello", ["scope:private"])

        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["path"], "/v1/default/banks/bank/memories/recall")
        self.assertEqual(seen["body"]["tags_match"], "all_strict")
        self.assertEqual(seen["body"]["types"], ["world", "experience", "observation"])

    async def test_retain_request_body_uses_async_item_level_tags(self):
        seen = {}

        async def handler(request):
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"success": True})

        client = _client_with_transport(handler)

        await client.retain("bank", "content", ["scope:group"], {"scope": "group"})

        self.assertEqual(seen["path"], "/v1/default/banks/bank/memories")
        self.assertIs(seen["body"]["async"], True)
        self.assertEqual(seen["body"]["items"][0]["tags"], ["scope:group"])
        self.assertNotIn("document_tags", seen["body"])

    async def test_status_maps_auth_and_permission_errors(self):
        async def handler(request):
            return httpx.Response(401, json={"detail": "nope"})

        client = _client_with_transport(handler)

        status = await client.check_status("bank")

        self.assertFalse(status.ok)
        self.assertIn("认证失败", status.message)

    async def test_invalid_json_raises_client_error(self):
        async def handler(request):
            return httpx.Response(200, content=b"not-json")

        client = _client_with_transport(handler)

        with self.assertRaises(HindsightClientError):
            await client.recall("bank", "hello", [])


def _client_with_transport(handler):
    client = HindsightClient("https://api.hindsight.vectorize.io", "hsk_test", 8)

    async def request_json(method, path, **kwargs):
        headers = {
            "Authorization": f"Bearer {client.api_key}",
            "Content-Type": "application/json",
        }
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(
            base_url=client.api_base,
            timeout=client.timeout,
            headers=headers,
            transport=transport,
        ) as http_client:
            response = await http_client.request(method, path, **kwargs)
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise HindsightClientError("Hindsight returned invalid JSON") from exc
            if not isinstance(data, dict):
                raise HindsightClientError("Hindsight returned an unexpected response shape")
            return data

    client._request_json = request_json
    return client


if __name__ == "__main__":
    unittest.main()
