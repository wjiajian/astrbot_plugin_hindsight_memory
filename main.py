from __future__ import annotations

from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.agent.message import TextPart

from .commands import PluginStateStore, build_help_text, run_manual_recall
from .hindsight_client import HindsightClient, HindsightClientError
from .memory_formatter import format_recall_results
from .scope import MemoryScope, build_scope_from_event


PLUGIN_NAME = "astrbot_plugin_hindsight_memory"


class HindsightMemoryPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self.config = config or {}
        self.store = PluginStateStore(StarTools.get_data_dir())
        self.salt = self.store.get_or_create_salt()

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        if not self._base_enabled():
            return
        scope = self._scope(event)
        if not self._scope_type_enabled(scope) or not self.store.is_scope_enabled(scope.scope_key):
            return
        if not self._config_complete():
            return

        query = _event_text(event)
        if not query:
            return

        client = self._client()
        try:
            raw = await client.recall(bank_id=self._bank_id(), query=query, tags=scope.tags)
            formatted = format_recall_results(raw, limit=self._recall_limit())
        except HindsightClientError as exc:
            _log_warning(f"Hindsight recall failed: {exc}")
            return

        if not formatted:
            return
        if not hasattr(req, "extra_user_content_parts"):
            _log_warning("ProviderRequest does not support extra_user_content_parts; skip Hindsight injection.")
            return

        req.extra_user_content_parts.append(_temporary_text_part(formatted))

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        if not self._base_enabled() or not _bool_config(self.config, "retain_enabled", True):
            return
        scope = self._scope(event)
        if not self._scope_type_enabled(scope) or not self.store.is_scope_enabled(scope.scope_key):
            return
        if not self._config_complete():
            return

        content = self._retain_content(event, resp)
        if not content:
            return

        try:
            await self._client().retain(
                bank_id=self._bank_id(),
                content=content,
                tags=scope.tags,
                metadata=scope.metadata,
            )
        except HindsightClientError as exc:
            _log_warning(f"Hindsight retain failed: {exc}")

    @filter.command_group("hindsight")
    def hindsight(self, event: AstrMessageEvent):
        pass

    @hindsight.command("status")
    async def hindsight_status(self, event: AstrMessageEvent):
        """检查 Hindsight Memory 配置和连接状态。"""
        scope = self._scope(event)
        lines = [
            "Hindsight Memory 状态",
            f"全局启用：{'是' if self._base_enabled() else '否'}",
            f"当前 scope：{scope.scope_type}",
            f"当前会话：{'开启' if self.store.is_scope_enabled(scope.scope_key) else '关闭'}",
            f"配置完整：{'是' if self._config_complete() else '否'}",
        ]
        if self._config_complete():
            status = await self._client().check_status(self._bank_id())
            lines.append(f"连接检查：{status.message}")
        else:
            lines.append("连接检查：跳过，请先填写 api_key 和 bank_id。")
        yield event.plain_result("\n".join(lines))

    @hindsight.command("recall")
    async def hindsight_recall(self, event: AstrMessageEvent, query: str):
        """手动检索当前会话 scope 下的 Hindsight 记忆。"""
        if not self._base_enabled():
            yield event.plain_result("Hindsight Memory 当前未启用。")
            return
        if not self._config_complete():
            yield event.plain_result("配置不完整，请先填写 api_key 和 bank_id。")
            return

        scope = self._scope(event)
        if not self._scope_type_enabled(scope):
            yield event.plain_result(f"当前 {scope.scope_type} scope 的记忆未启用。")
            return
        if not self.store.is_scope_enabled(scope.scope_key):
            yield event.plain_result("当前会话记忆已关闭。")
            return

        try:
            result = await run_manual_recall(
                self._client(),
                bank_id=self._bank_id(),
                query=query,
                tags=scope.tags,
                limit=self._recall_limit(),
            )
        except HindsightClientError as exc:
            _log_warning(f"Hindsight manual recall failed: {exc}")
            result = f"手动检索失败：{exc}"
        yield event.plain_result(result)

    @hindsight.command("on")
    async def hindsight_on(self, event: AstrMessageEvent):
        """启用当前会话的 Hindsight 记忆。"""
        scope = self._scope(event)
        self.store.set_scope_enabled(scope.scope_key, True)
        yield event.plain_result("已启用当前会话 Hindsight 记忆。")

    @hindsight.command("off")
    async def hindsight_off(self, event: AstrMessageEvent):
        """关闭当前会话的 Hindsight 记忆。"""
        scope = self._scope(event)
        self.store.set_scope_enabled(scope.scope_key, False)
        yield event.plain_result("已关闭当前会话 Hindsight 记忆。")

    @hindsight.command("help")
    async def hindsight_help(self, event: AstrMessageEvent):
        """显示 Hindsight Memory 命令帮助。"""
        scope = self._scope(event)
        yield event.plain_result(build_help_text(self.store.is_scope_enabled(scope.scope_key)))

    def _client(self) -> HindsightClient:
        return HindsightClient(
            api_base=str(self.config.get("api_base") or "https://api.hindsight.vectorize.io"),
            api_key=str(self.config.get("api_key") or ""),
            timeout_seconds=int(self.config.get("request_timeout_seconds") or 8),
        )

    def _scope(self, event: AstrMessageEvent) -> MemoryScope:
        scope = build_scope_from_event(event, self.salt)
        if scope.scope_type == "private" and _event_looks_like_group(event):
            _log_debug("Hindsight scope fallback: group-like event has no group_id; using private scope.")
        return scope

    def _base_enabled(self) -> bool:
        return _bool_config(self.config, "enabled", True)

    def _config_complete(self) -> bool:
        return bool(str(self.config.get("api_key") or "").strip() and self._bank_id())

    def _bank_id(self) -> str:
        return str(self.config.get("bank_id") or "").strip()

    def _recall_limit(self) -> int:
        try:
            return max(1, int(self.config.get("recall_limit") or 5))
        except (TypeError, ValueError):
            return 5

    def _scope_type_enabled(self, scope: MemoryScope) -> bool:
        if scope.scope_type == "group":
            return _bool_config(self.config, "enable_group_memory", True)
        return _bool_config(self.config, "enable_private_memory", True)

    def _retain_content(self, event: AstrMessageEvent, resp: LLMResponse) -> str:
        parts: list[str] = []
        if _bool_config(self.config, "retain_user_message", True):
            user_text = _event_text(event)
            if user_text:
                parts.append(f"User said: {user_text}")
        if _bool_config(self.config, "retain_assistant_message", True):
            assistant_text = _response_text(resp)
            if assistant_text:
                parts.append(f"Assistant replied: {assistant_text}")
        return "\n".join(parts)


def _event_text(event: Any) -> str:
    return str(getattr(event, "message_str", "") or "").strip()


def _response_text(resp: Any) -> str:
    return str(getattr(resp, "completion_text", "") or "").strip()


def _event_looks_like_group(event: Any) -> bool:
    method = getattr(event, "get_message_type", None)
    if callable(method):
        try:
            return str(method()).lower() == "group"
        except (AttributeError, TypeError, ValueError):
            return False
    message_obj = getattr(event, "message_obj", None)
    message_type = getattr(message_obj, "type", None) or getattr(message_obj, "message_type", None)
    return str(message_type).lower() == "group"


def _temporary_text_part(text: str) -> Any:
    try:
        part = TextPart(text=text)
    except TypeError:
        part = TextPart(text)
    return part.mark_as_temp()


def _bool_config(config: Any, key: str, default: bool) -> bool:
    value = config.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


def _log_warning(message: str) -> None:
    if logger is not None:
        logger.warning(message)


def _log_debug(message: str) -> None:
    if logger is not None:
        logger.debug(message)
