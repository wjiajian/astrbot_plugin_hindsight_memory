from __future__ import annotations

from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, StarTools
from astrbot.core.agent.message import TextPart

from .commands import PluginStateStore, build_help_text, run_manual_recall_for_tag_sets
from .hindsight_client import HindsightClient, HindsightClientError
from .memory_formatter import extract_memories, extract_memory_texts, format_recall_results
from .retention_policy import (
    RetainDecision,
    apply_ai_retention_result,
    build_ai_retention_prompt,
    decide_retention,
    dedupe_action,
    should_write_raw_conversation,
)
from .scope import MemoryScope, MemoryScopes, build_scopes_from_event


PLUGIN_NAME = "astrbot_plugin_hindsight_memory"


class HindsightMemoryPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None) -> None:
        super().__init__(context)
        self._context = context
        self.config = config or {}
        self.store = PluginStateStore(StarTools.get_data_dir())
        self.salt = self.store.get_or_create_salt()
        self.hindsight_client: HindsightClient | None = None
        self.hindsight_client_signature: tuple[str, str, int] | None = None

    async def terminate(self):
        if self.hindsight_client is not None:
            await self.hindsight_client.aclose()

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        if not self._base_enabled():
            return
        scopes = self._scopes(event)
        if not self._scope_type_enabled(scopes.primary) or not self.store.is_scope_enabled(scopes.primary.scope_key):
            return
        if not self._config_complete():
            return

        query = _event_text(event)
        if not query:
            return

        client = await self._client()
        try:
            memories = []
            for recall_scope in scopes.recall_scopes:
                raw = await client.recall(bank_id=self._bank_id(), query=query, tags=recall_scope.tags)
                memories.extend(extract_memories(raw))
            formatted = format_recall_results(memories, limit=self._recall_limit())
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
        scopes = self._scopes(event)
        if not self._scope_type_enabled(scopes.primary) or not self.store.is_scope_enabled(scopes.primary.scope_key):
            return
        if not self._config_complete():
            return

        user_text = _event_text(event)
        assistant_text = _response_text(resp)
        decision = await self._retention_decision(event, user_text, assistant_text, scopes.primary.scope_type)
        if not decision.should_retain:
            _log_debug(f"Hindsight retain skipped: {decision.reason}")
            return

        content = self._retain_content(user_text, assistant_text, decision)
        if not content:
            return

        try:
            client = await self._client()
            for retain_scope in scopes.retain_scopes:
                if retain_scope.scope_type not in decision.target_scope_types:
                    continue
                retain_action = await self._retain_dedupe_action(client, content, retain_scope, decision)
                if retain_action == "duplicate":
                    _log_debug(f"Hindsight retain skipped duplicate: {retain_scope.scope_type}")
                    continue
                await client.retain(
                    bank_id=self._bank_id(),
                    content=content,
                    tags=retain_scope.tags,
                    metadata=self._retain_metadata(retain_scope.metadata, decision, retain_action),
                )
        except HindsightClientError as exc:
            _log_warning(f"Hindsight retain failed: {exc}")

    @filter.command_group("hindsight")
    def hindsight(self, event: AstrMessageEvent):
        pass

    @hindsight.command("status")
    async def hindsight_status(self, event: AstrMessageEvent):
        """检查 Hindsight Memory 配置和连接状态。"""
        scope = self._scopes(event).primary
        lines = [
            "Hindsight Memory 状态",
            f"全局启用：{'是' if self._base_enabled() else '否'}",
            f"当前 scope：{scope.scope_type}",
            f"当前会话：{'开启' if self.store.is_scope_enabled(scope.scope_key) else '关闭'}",
            f"配置完整：{'是' if self._config_complete() else '否'}",
        ]
        if self._config_complete():
            status = await (await self._client()).check_status(self._bank_id())
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

        scopes = self._scopes(event)
        scope = scopes.primary
        if not self._scope_type_enabled(scope):
            yield event.plain_result(f"当前 {scope.scope_type} scope 的记忆未启用。")
            return
        if not self.store.is_scope_enabled(scope.scope_key):
            yield event.plain_result("当前会话记忆已关闭。")
            return

        try:
            result = await run_manual_recall_for_tag_sets(
                await self._client(),
                bank_id=self._bank_id(),
                query=query,
                tag_sets=[recall_scope.tags for recall_scope in scopes.recall_scopes],
                limit=self._recall_limit(),
            )
        except HindsightClientError as exc:
            _log_warning(f"Hindsight manual recall failed: {exc}")
            result = f"手动检索失败：{exc}"
        yield event.plain_result(result)

    @hindsight.command("on")
    async def hindsight_on(self, event: AstrMessageEvent):
        """启用当前会话的 Hindsight 记忆。"""
        scope = self._scopes(event).primary
        self.store.set_scope_enabled(scope.scope_key, True)
        yield event.plain_result("已启用当前会话 Hindsight 记忆。")

    @hindsight.command("off")
    async def hindsight_off(self, event: AstrMessageEvent):
        """关闭当前会话的 Hindsight 记忆。"""
        scope = self._scopes(event).primary
        self.store.set_scope_enabled(scope.scope_key, False)
        yield event.plain_result("已关闭当前会话 Hindsight 记忆。")

    @hindsight.command("help")
    async def hindsight_help(self, event: AstrMessageEvent):
        """显示 Hindsight Memory 命令帮助。"""
        scope = self._scopes(event).primary
        yield event.plain_result(build_help_text(self.store.is_scope_enabled(scope.scope_key)))

    async def _client(self) -> HindsightClient:
        signature = self._client_signature()
        if self.hindsight_client is not None and self.hindsight_client_signature == signature:
            return self.hindsight_client

        if self.hindsight_client is not None:
            await self.hindsight_client.aclose()

        api_base, api_key, timeout_seconds = signature
        self.hindsight_client = HindsightClient(
            api_base=api_base,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
        self.hindsight_client_signature = signature
        return self.hindsight_client

    def _client_signature(self) -> tuple[str, str, int]:
        return (
            str(self.config.get("api_base") or "https://api.hindsight.vectorize.io"),
            str(self.config.get("api_key") or ""),
            self._request_timeout_seconds(),
        )

    def _scopes(self, event: AstrMessageEvent) -> MemoryScopes:
        scopes = build_scopes_from_event(event, self.salt)
        if scopes.primary.scope_type == "private" and _event_looks_like_group(event):
            _log_debug("Hindsight scope fallback: group-like event has no group_id; using private scope.")
        return scopes

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

    def _request_timeout_seconds(self) -> int:
        try:
            return max(1, int(self.config.get("request_timeout_seconds") or 8))
        except (TypeError, ValueError):
            return 8

    def _scope_type_enabled(self, scope: MemoryScope) -> bool:
        if scope.scope_type in {"group_shared", "group_member"}:
            return _bool_config(self.config, "enable_group_memory", True)
        return _bool_config(self.config, "enable_private_memory", True)

    async def _retention_decision(
        self,
        event: AstrMessageEvent,
        user_text: str,
        assistant_text: str,
        primary_scope_type: str,
    ) -> RetainDecision:
        decision = decide_retention(user_text, assistant_text, primary_scope_type, self.config)
        if not decision.should_retain or decision.reason == "all_mode":
            return decision
        if not _bool_config(self.config, "retain_ai_enabled", False):
            return decision

        prompt = build_ai_retention_prompt(user_text, assistant_text, primary_scope_type)
        try:
            response_text = await _call_ai_retention(self._context, event, prompt, self.config)
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            _log_warning(f"Hindsight AI retention fallback to rules: {exc}")
            return decision

        ai_decision = apply_ai_retention_result(decision, response_text, primary_scope_type, self.config)
        if ai_decision is None:
            _log_warning("Hindsight AI retention returned invalid JSON; fallback to rules.")
            return decision
        return ai_decision

    async def _retain_dedupe_action(
        self,
        client: HindsightClient,
        content: str,
        retain_scope: MemoryScope,
        decision: RetainDecision,
    ) -> str:
        if not _bool_config(self.config, "retain_dedupe_enabled", True):
            return "not_checked"
        try:
            raw = await client.recall(bank_id=self._bank_id(), query=content, tags=retain_scope.tags)
            existing_texts = extract_memory_texts(raw, limit=self._retain_dedupe_limit())
        except HindsightClientError as exc:
            _log_warning(f"Hindsight retain dedupe failed; continue writing: {exc}")
            return "dedupe_failed"
        return dedupe_action(content, existing_texts, self._retain_dedupe_threshold(), decision.memory_type)

    def _retain_dedupe_limit(self) -> int:
        try:
            return max(1, int(self.config.get("retain_dedupe_limit") or 5))
        except (TypeError, ValueError):
            return 5

    def _retain_dedupe_threshold(self) -> float:
        try:
            return min(1.0, max(0.0, float(self.config.get("retain_dedupe_threshold", 0.85))))
        except (TypeError, ValueError):
            return 0.85

    def _retain_metadata(
        self,
        base_metadata: dict[str, Any],
        decision: RetainDecision,
        retain_action: str,
    ) -> dict[str, Any]:
        metadata = dict(base_metadata)
        metadata.update(
            {
                "retention_reason": decision.reason,
                "retention_sensitivity": decision.sensitivity,
                "retention_type": decision.memory_type,
                "retention_source": decision.source,
                "retention_confidence": decision.confidence,
                "retention_action": retain_action,
            }
        )
        return metadata

    def _retain_content(self, user_text: str, assistant_text: str, decision: RetainDecision) -> str:
        if decision.memory_text and not should_write_raw_conversation(decision, self.config):
            return decision.memory_text
        parts: list[str] = []
        if decision.keep_user and _bool_config(self.config, "retain_user_message", True) and user_text:
            parts.append(f"User said: {user_text}")
        if decision.keep_assistant and _bool_config(self.config, "retain_assistant_message", True) and assistant_text:
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


async def _call_ai_retention(context: Any, event: Any, prompt: str, config: Any) -> str:
    provider_id = await _resolve_ai_provider_id(context, event, config)
    if not provider_id:
        raise RuntimeError("no AI retention provider selected")

    selected_provider_id = str(config.get("retain_ai_provider_id") or "").strip()
    try:
        return await _llm_generate_text(context, provider_id, prompt)
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        if not selected_provider_id or not _bool_config(config, "retain_ai_fallback_to_current_provider", False):
            raise
        fallback_provider_id = await _current_chat_provider_id(context, event)
        if not fallback_provider_id or fallback_provider_id == selected_provider_id:
            raise
        _log_warning(f"Hindsight AI retention selected provider failed; fallback to current provider: {exc}")
        return await _llm_generate_text(context, fallback_provider_id, prompt)


async def _llm_generate_text(context: Any, provider_id: str, prompt: str) -> str:
    llm_generate = getattr(context, "llm_generate", None)
    if not callable(llm_generate):
        raise RuntimeError("AstrBot context does not support llm_generate")
    system_prompt = "You classify chat turns for long-term memory. Return JSON only."
    attempts = (
        {"chat_provider_id": provider_id, "prompt": prompt, "system_prompt": system_prompt},
        {"chat_provider_id": provider_id, "prompt": prompt},
    )
    last_error: Exception | None = None
    for kwargs in attempts:
        try:
            response = await _maybe_await(llm_generate(**kwargs))
            response_text = _response_text(response) or str(response or "")
            if response_text.strip():
                return response_text
        except TypeError as exc:
            last_error = exc
            continue
    raise RuntimeError(f"llm_generate call failed: {last_error}")


async def _resolve_ai_provider_id(context: Any, event: Any, config: Any) -> str:
    selected_provider_id = str(config.get("retain_ai_provider_id") or "").strip()
    if selected_provider_id:
        return selected_provider_id
    return await _current_chat_provider_id(context, event)


async def _current_chat_provider_id(context: Any, event: Any) -> str:
    umo = str(getattr(event, "unified_msg_origin", "") or "")
    method = getattr(context, "get_current_chat_provider_id", None)
    if not callable(method):
        return ""
    try:
        provider_id = method(umo=umo)
    except TypeError:
        provider_id = method(umo)
    return str(await _maybe_await(provider_id) or "").strip()


async def _maybe_await(value: Any) -> Any:
    if hasattr(value, "__await__"):
        return await value
    return value


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
