from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import secrets
from typing import TYPE_CHECKING

from astrbot.api import logger

from .memory_formatter import extract_memories, format_recall_results

if TYPE_CHECKING:
    from .hindsight_client import HindsightClient


SALT_FILE = "salt.txt"
STATE_FILE = "scope_state.json"


@dataclass
class ScopeSwitchState:
    disabled_scopes: set[str]


class PluginStateStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.salt_path = self.data_dir / SALT_FILE
        self.state_path = self.data_dir / STATE_FILE

    def get_or_create_salt(self) -> str:
        if self.salt_path.exists():
            salt = self.salt_path.read_text(encoding="utf-8").strip()
            if salt:
                return salt

        salt = secrets.token_hex(32)
        self.salt_path.write_text(salt, encoding="utf-8")
        return salt

    def is_scope_enabled(self, scope_key: str) -> bool:
        return scope_key not in self._load_state().disabled_scopes

    def set_scope_enabled(self, scope_key: str, enabled: bool) -> None:
        state = self._load_state()
        if enabled:
            state.disabled_scopes.discard(scope_key)
        else:
            state.disabled_scopes.add(scope_key)
        self._save_state(state)

    def _load_state(self) -> ScopeSwitchState:
        if not self.state_path.exists():
            return ScopeSwitchState(disabled_scopes=set())
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning(f"Hindsight scope state file is invalid JSON: {self.state_path}: {exc}")
            return ScopeSwitchState(disabled_scopes=set())
        except OSError as exc:
            logger.warning(f"Hindsight scope state file could not be read: {self.state_path}: {exc}")
            return ScopeSwitchState(disabled_scopes=set())
        disabled = raw.get("disabled_scopes", [])
        if not isinstance(disabled, list):
            disabled = []
        return ScopeSwitchState(disabled_scopes={str(item) for item in disabled})

    def _save_state(self, state: ScopeSwitchState) -> None:
        payload = {"disabled_scopes": sorted(state.disabled_scopes)}
        tmp_path = self.state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.state_path)


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


async def run_manual_recall(client: HindsightClient, bank_id: str, query: str, tags: list[str], limit: int) -> str:
    return await run_manual_recall_for_tag_sets(client, bank_id, query, [tags], limit)


async def run_manual_recall_for_tag_sets(
    client: HindsightClient,
    bank_id: str,
    query: str,
    tag_sets: list[list[str]],
    limit: int,
) -> str:
    memories = []
    for tags in tag_sets:
        raw = await client.recall(bank_id=bank_id, query=query, tags=tags)
        memories.extend(extract_memories(raw))
    formatted = format_recall_results(memories, limit=limit)
    if not formatted:
        return "当前会话 scope 下没有召回到相关记忆。"
    return formatted
