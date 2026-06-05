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
        self.addAsyncCleanup(client.aclose)

        await client.recall("bank", "hello", ["scope:private"])

        self.assertEqual(seen["method"], "POST")
        self.assertEqual(seen["path"], "/v1/default/banks/bank/memories/recall")
        self.assertEqual(seen["body"]["tags_match"], "all_strict")
        self.assertEqual(seen["body"]["types"], ["world", "experience", "observation"])

    async def test_api_base_subpath_is_preserved(self):
        seen = {}

        async def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(200, json={"results": []})

        client = _client_with_transport(handler, api_base="https://proxy.example.com/hindsight_api")
        self.addAsyncCleanup(client.aclose)

        await client.recall("bank", "hello", ["scope:private"])

        self.assertEqual(client.api_base, "https://proxy.example.com/hindsight_api/")
        self.assertEqual(
            seen["url"],
            "https://proxy.example.com/hindsight_api/v1/default/banks/bank/memories/recall",
        )

    async def test_api_base_trailing_slash_is_preserved(self):
        async def handler(request):
            return httpx.Response(200, json={"results": []})

        client = _client_with_transport(handler, api_base="https://proxy.example.com/hindsight_api/")
        self.addAsyncCleanup(client.aclose)

        self.assertEqual(client.api_base, "https://proxy.example.com/hindsight_api/")

    async def test_retain_request_body_uses_async_item_level_tags(self):
        seen = {}

        async def handler(request):
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content.decode())
            return httpx.Response(200, json={"success": True})

        client = _client_with_transport(handler)
        self.addAsyncCleanup(client.aclose)

        await client.retain("bank", "content", ["scope:group"], {"scope": "group"})

        self.assertEqual(seen["path"], "/v1/default/banks/bank/memories")
        self.assertIs(seen["body"]["async"], True)
        self.assertEqual(seen["body"]["items"][0]["tags"], ["scope:group"])
        self.assertNotIn("document_tags", seen["body"])

    async def test_status_maps_auth_and_permission_errors(self):
        async def handler(request):
            return httpx.Response(401, json={"detail": "nope"})

        client = _client_with_transport(handler)
        self.addAsyncCleanup(client.aclose)

        status = await client.check_status("bank")

        self.assertFalse(status.ok)
        self.assertIn("认证失败", status.message)

    async def test_invalid_json_raises_client_error(self):
        async def handler(request):
            return httpx.Response(200, content=b"not-json")

        client = _client_with_transport(handler)
        self.addAsyncCleanup(client.aclose)

        with self.assertRaises(HindsightClientError):
            await client.recall("bank", "hello", [])

    async def test_http_status_errors_are_wrapped(self):
        async def handler(request):
            return httpx.Response(403, json={"detail": "nope"})

        client = _client_with_transport(handler)
        self.addAsyncCleanup(client.aclose)

        with self.assertRaises(HindsightClientError) as context:
            await client.recall("bank", "hello", [])

        self.assertEqual(context.exception.status_code, 403)

    async def test_client_reuses_async_client_until_closed(self):
        async def handler(request):
            return httpx.Response(200, json={"results": []})

        client = _client_with_transport(handler)

        self.assertIsNone(client._client)

        await client.recall("bank", "first", [])
        shared_client = client._client
        await client.recall("bank", "second", [])

        self.assertIs(client._client, shared_client)
        self.assertIsNotNone(client._client)
        self.assertFalse(client._client.is_closed)

        await client.aclose()
        self.assertIsNone(client._client)

    async def test_retries_transient_server_errors(self):
        attempts = 0

        async def handler(request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(502, json={"detail": "try again"})
            return httpx.Response(200, json={"results": []})

        client = _client_with_transport(handler)
        self.addAsyncCleanup(client.aclose)

        await client.recall("bank", "hello", [])

        self.assertEqual(attempts, 2)

    async def test_retain_does_not_retry_transient_server_errors(self):
        attempts = 0

        async def handler(request):
            nonlocal attempts
            attempts += 1
            return httpx.Response(502, json={"detail": "try again"})

        client = _client_with_transport(handler)
        self.addAsyncCleanup(client.aclose)

        with self.assertRaises(HindsightClientError):
            await client.retain("bank", "content", ["scope:private"])

        self.assertEqual(attempts, 1)

    async def test_does_not_retry_client_errors(self):
        attempts = 0

        async def handler(request):
            nonlocal attempts
            attempts += 1
            return httpx.Response(403, json={"detail": "nope"})

        client = _client_with_transport(handler)
        self.addAsyncCleanup(client.aclose)

        with self.assertRaises(HindsightClientError):
            await client.recall("bank", "hello", [])

        self.assertEqual(attempts, 1)


def _client_with_transport(handler, api_base="https://api.hindsight.vectorize.io"):
    return HindsightClient(
        api_base,
        "hsk_test",
        8,
        transport=httpx.MockTransport(handler),
        retry_base_delay_seconds=0,
    )


if __name__ == "__main__":
    unittest.main()
