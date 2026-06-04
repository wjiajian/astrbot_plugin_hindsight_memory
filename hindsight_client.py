from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


RECALL_TYPES = ["world", "experience", "observation"]
DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_BASE_DELAY_SECONDS = 0.25


class HindsightClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        kind: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind


@dataclass(frozen=True)
class HindsightStatus:
    ok: bool
    message: str


class HindsightClient:
    def __init__(
        self,
        api_base: str,
        api_key: str,
        timeout_seconds: int = 8,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_base_delay_seconds: float = DEFAULT_RETRY_BASE_DELAY_SECONDS,
    ) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = httpx.Timeout(float(timeout_seconds))
        self.transport = transport
        self.max_retries = max(0, max_retries)
        self.retry_base_delay_seconds = max(0.0, retry_base_delay_seconds)
        self._client: httpx.AsyncClient | None = None

    async def recall(self, bank_id: str, query: str, tags: list[str]) -> dict[str, Any]:
        payload = {
            "query": query,
            "types": RECALL_TYPES,
            "tags": tags,
            "tags_match": "all_strict",
        }
        return await self._request_json(
            "POST",
            f"/v1/default/banks/{bank_id}/memories/recall",
            retryable=True,
            json=payload,
        )

    async def retain(
        self,
        bank_id: str,
        content: str,
        tags: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        item: dict[str, Any] = {
            "content": content,
            "tags": tags,
        }
        if metadata:
            item["metadata"] = metadata

        payload = {
            "async": True,
            "items": [item],
        }
        return await self._request_json(
            "POST",
            f"/v1/default/banks/{bank_id}/memories",
            retryable=False,
            json=payload,
        )

    async def check_status(self, bank_id: str) -> HindsightStatus:
        try:
            await self._request_json(
                "GET",
                f"/v1/default/banks/{bank_id}/tags",
                retryable=True,
                params={"limit": 1},
            )
        except HindsightClientError as exc:
            if exc.kind == "timeout":
                return HindsightStatus(False, "连接超时，请检查网络或 request_timeout_seconds。")
            status = exc.status_code
            if status == 401:
                return HindsightStatus(False, "认证失败：API Key 无效或未提供。")
            if status == 403:
                return HindsightStatus(False, "权限不足：请确认 API Key 有访问该 Bank 的权限。")
            if status == 404:
                return HindsightStatus(False, "Bank 不存在：请检查 bank_id。")
            if status is not None:
                return HindsightStatus(False, f"Hindsight 返回 HTTP {status}。")
            return HindsightStatus(False, f"连接失败：{exc}")
        return HindsightStatus(True, "Hindsight Cloud 连接正常。")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        retryable: bool,
        **kwargs: Any,
    ) -> dict[str, Any]:
        attempts = self.max_retries + 1 if retryable else 1
        for attempt in range(attempts):
            try:
                return await self._request_json_once(method, path, **kwargs)
            except HindsightClientError as exc:
                if attempt >= attempts - 1 or not _should_retry(exc):
                    raise
                await asyncio.sleep(self.retry_base_delay_seconds * (2**attempt))
        raise HindsightClientError("Hindsight request failed after retries")

    async def _request_json_once(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            client = await self._get_client()
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise HindsightClientError("Hindsight returned invalid JSON") from exc
        except httpx.TimeoutException as exc:
            raise HindsightClientError("Hindsight request timed out", kind="timeout") from exc
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            raise HindsightClientError(
                f"Hindsight returned HTTP {status_code}",
                status_code=status_code,
                kind="http_status",
            ) from exc
        except httpx.RequestError as exc:
            raise HindsightClientError(f"Hindsight request failed: {exc}", kind="network") from exc

        if not isinstance(data, dict):
            raise HindsightClientError("Hindsight returned an unexpected response shape")
        return data

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.api_base,
                timeout=self.timeout,
                headers=self._headers(),
                transport=self.transport,
            )
        return self._client

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }


def _should_retry(exc: HindsightClientError) -> bool:
    if exc.kind in {"timeout", "network"}:
        return True
    return exc.status_code is not None and exc.status_code >= 500
