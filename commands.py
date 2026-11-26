from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
import json
import logging
import secrets
import uuid
from typing import Any, Sequence

from .hindsight_client import HindsightClient, HindsightClientError
from .memory_formatter import (
    DEFAULT_ITEM_MAX_CHARS,
    MAX_EXTRACT_DEPTH,
    extract_memories,
    format_recall_results,
    merge_ranked_memories,
)


logger = logging.getLogger(__name__)
SALT_FILE = "salt.txt"
STATE_FILE = "scope_state.json"
STATE_VERSION = 2
STATE_MARKER_FILE = "scope_state.version"


@dataclass
class ScopeSwitchState:
    disabled_scopes: set[str]
    private_scopes: set[str] = field(default_factory=set)
    private_conversations: set[str] = field(default_factory=set)


class PluginStateStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.salt_path = self.data_dir / SALT_FILE
        self.state_path = self.data_dir / STATE_FILE
        self.marker_path = self.data_dir / STATE_MARKER_FILE

    def get_or_create_salt(self) -> str:
        if self.salt_path.exists():
            salt = self.salt_path.read_text(encoding="utf-8").strip()
            if salt:
                return salt

        salt = secrets.token_hex(32)
        self.salt_path.write_text(salt, encoding="utf-8")
        return salt

    def is_scope_enabled(self, scope_key: str) -> bool:
        state = self._load_state()
        return state is not None and scope_key not in state.disabled_scopes

    def set_scope_enabled(self, scope_key: str, enabled: bool) -> None:
        state = self._require_state()
        if enabled:
            state.disabled_scopes.discard(scope_key)
        else:
            state.disabled_scopes.add(scope_key)
        self._save_state(state)

    def is_private_scope(self, scope_key: str) -> bool | None:
        """Return unknown (not normal mode) if persisted state is unreadable."""
        state = self._load_state()
        return None if state is None else scope_key in state.private_scopes

    def set_private_scope(self, scope_key: str, enabled: bool) -> None:
        state = self._require_state()
        if enabled:
            state.private_scopes.add(scope_key)
        else:
            state.private_scopes.discard(scope_key)
        self._save_state(state)

    def is_private_conversation(self, conversation_id: str) -> bool | None:
        if not conversation_id:
            return False
        state = self._load_state()
        return None if state is None else conversation_id in state.private_conversations

    def mark_private_conversation(self, conversation_id: str, private: bool) -> None:
        if not conversation_id:
            return
        state = self._require_state()
        if private:
            state.private_conversations.add(conversation_id)
        else:
            state.private_conversations.discard(conversation_id)
        self._save_state(state)

    def _require_state(self) -> ScopeSwitchState:
        state = self._load_state()
        if state is None:
            raise OSError("scope state is unreadable; refusing to overwrite it")
        return state

    def _load_state(self) -> ScopeSwitchState | None:
        try:
            text = self.state_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            if self.marker_path.exists():
                logger.warning("Hindsight scope state file is missing; shared routing paused")
                return None
            return ScopeSwitchState(disabled_scopes=set())
        except OSError as exc:
            logger.warning("Hindsight scope state unavailable: %s", exc)
            return None
        try:
            raw = json.loads(text)
            if not isinstance(raw, dict):
                raise ValueError("scope state must be an object")
            disabled = raw.get("disabled_scopes", [])
            private = raw.get("private_scopes", [])
            conversations = raw.get("private_conversations", [])
            if not all(isinstance(item, list) for item in (disabled, private, conversations)):
                raise ValueError("scope state entries must be lists")
            if raw.get("version") != STATE_VERSION and self.marker_path.exists():
                raise ValueError("scope state version is missing or unknown")
        except ValueError as exc:
            logger.warning("Hindsight scope state unavailable: %s", exc)
            return None
        return ScopeSwitchState(
            disabled_scopes={str(item) for item in disabled},
            private_scopes={str(item) for item in private},
            private_conversations={str(item) for item in conversations},
        )

    def _save_state(self, state: ScopeSwitchState) -> None:
        payload = {
            "version": STATE_VERSION,
            "disabled_scopes": sorted(state.disabled_scopes),
            "private_conversations": sorted(state.private_conversations),
            "private_scopes": sorted(state.private_scopes),
        }
        tmp_path = self.state_path.with_name(f"{self.state_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp_path.replace(self.state_path)
            self.marker_path.write_text(str(STATE_VERSION), encoding="utf-8")
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


def build_help_text(scope_enabled: bool | None = None) -> str:
    lines = [
        "Hindsight Memory 命令：",
        "/hindsight status - 检查配置和 Hindsight 连通性",
        "/hindsight recall <query> - 在当前会话 scope 下手动检索记忆",
        "/hindsight on - 启用当前会话记忆",
        "/hindsight off - 关闭当前会话记忆",
        "/hindsight help - 显示帮助",
    ]
    if scope_enabled is not None:
        lines.append(f"当前会话记忆：{'开启' if scope_enabled else '关闭'}")
    return "\n".join(lines)


async def run_manual_recall(
    client: HindsightClient,
    bank_id: str,
    query: str,
    tags: list[str],
    limit: int,
    item_max_chars: int = DEFAULT_ITEM_MAX_CHARS,
    max_extract_depth: int = MAX_EXTRACT_DEPTH,
    queries: Sequence[str] | None = None,
) -> str:
    return await run_manual_recall_for_tag_sets(
        client,
        bank_id,
        query,
        [tags],
        limit,
        item_max_chars,
        max_extract_depth,
        queries,
    )


async def run_manual_recall_for_tag_sets(
    client: HindsightClient,
    bank_id: str,
    query: str,
    tag_sets: list[list[str]],
    limit: int,
    item_max_chars: int = DEFAULT_ITEM_MAX_CHARS,
    max_extract_depth: int = MAX_EXTRACT_DEPTH,
    queries: Sequence[str] | None = None,
    empty_message: str = "当前会话 scope 下没有召回到相关记忆。",
    guidance: bool = False,
) -> str:
    return await run_recall_for_targets(
        client, [(bank_id, tuple(tags)) for tags in tag_sets], query, limit,
        item_max_chars, max_extract_depth, queries, empty_message, guidance,
    )


async def run_recall_for_targets(
    client: HindsightClient,
    targets: Sequence[tuple[str, tuple[str, ...]]],
    query: str,
    limit: int,
    item_max_chars: int = DEFAULT_ITEM_MAX_CHARS,
    max_extract_depth: int = MAX_EXTRACT_DEPTH,
    queries: Sequence[str] | None = None,
    empty_message: str = "当前会话 scope 下没有召回到相关记忆。",
    guidance: bool = False,
) -> str:
    recall_queries = _recall_queries(query, queries)
    results = await asyncio.gather(
        *(
            client.recall(bank_id=bank_id, query=recall_query, tags=list(tags))
            for bank_id, tags in targets
            for recall_query in recall_queries
        ),
        return_exceptions=True,
    )
    ranked_lists: list[list[Any]] = []
    failures: list[HindsightClientError] = []
    for result in results:
        if isinstance(result, HindsightClientError):
            failures.append(result)
        elif isinstance(result, BaseException):
            raise result
        else:
            ranked_lists.append(extract_memories(result))
    if failures and not ranked_lists:
        raise failures[0]
    if failures and logger is not None:
        logger.warning(f"Hindsight recall partially failed ({len(failures)}/{len(results)}): {failures[0]}")
    memories = merge_ranked_memories(ranked_lists, max_extract_depth=max_extract_depth)
    formatted = format_recall_results(
        memories,
        limit=limit,
        item_max_chars=item_max_chars,
        max_extract_depth=max_extract_depth,
        guidance=guidance,
    )
    if not formatted:
        return empty_message
    return formatted


def _recall_queries(query: str, queries: Sequence[str] | None) -> list[str]:
    values = list(queries or [])
    if query not in values:
        values.insert(0, query)
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
