from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


RECALL_TYPES = ["world", "experience", "observation"]


class HindsightClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class HindsightStatus:
    ok: bool
    message: str


class HindsightClient:
    def __init__(self, api_base: str, api_key: str, timeout_seconds: int = 8) -> None:
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = httpx.Timeout(float(timeout_seconds))

    async def recall(self, bank_id: str, query: str, tags: list[str]) -> dict[str, Any]:
        payload = {
            "query": query,
            "types": RECALL_TYPES,
            "tags": tags,
            "tags_match": "all_strict",
        }
        return await self._request_json("POST", f"/v1/default/banks/{bank_id}/memories/recall", json=payload)

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
        return await self._request_json("POST", f"/v1/default/banks/{bank_id}/memories", json=payload)

    async def check_status(self, bank_id: str) -> HindsightStatus:
        try:
            await self._request_json("GET", f"/v1/default/banks/{bank_id}/tags", params={"limit": 1})
        except httpx.TimeoutException:
            return HindsightStatus(False, "连接超时，请检查网络或 request_timeout_seconds。")
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 401:
                return HindsightStatus(False, "认证失败：API Key 无效或未提供。")
            if status == 403:
                return HindsightStatus(False, "权限不足：请确认 API Key 有访问该 Bank 的权限。")
            if status == 404:
                return HindsightStatus(False, "Bank 不存在：请检查 bank_id。")
            return HindsightStatus(False, f"Hindsight 返回 HTTP {status}。")
        except Exception as exc:
            return HindsightStatus(False, f"连接失败：{exc}")
        return HindsightStatus(True, "Hindsight Cloud 连接正常。")

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(base_url=self.api_base, timeout=self.timeout, headers=headers) as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise HindsightClientError("Hindsight returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise HindsightClientError("Hindsight returned an unexpected response shape")
        return data
