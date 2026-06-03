from __future__ import annotations

from typing import Any


DEFAULT_ITEM_MAX_CHARS = 360


def format_recall_results(raw: Any, limit: int, item_max_chars: int = DEFAULT_ITEM_MAX_CHARS) -> str:
    memories = extract_memories(raw)
    if not memories:
        return ""

    lines: list[str] = []
    for memory in memories[: max(0, limit)]:
        text = _extract_text(memory)
        if not text:
            continue
        lines.append(f"- {_truncate(_normalize_text(text), item_max_chars)}")

    if not lines:
        return ""
    return "<hindsight_memory>\n" + "\n".join(lines) + "\n</hindsight_memory>"


def extract_memories(raw: Any) -> list[Any]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, dict):
        return []

    for key in ("results", "memories", "items", "data"):
        value = raw.get(key)
        if isinstance(value, list):
            return value
    return []


def _extract_text(memory: Any) -> str:
    if isinstance(memory, str):
        return memory
    if not isinstance(memory, dict):
        return ""

    for key in ("text", "content", "memory", "fact", "summary"):
        value = memory.get(key)
        if isinstance(value, str) and value.strip():
            return value

    nested = memory.get("memory")
    if isinstance(nested, dict):
        return _extract_text(nested)

    observation = memory.get("observation")
    if isinstance(observation, dict):
        return _extract_text(observation)

    return ""


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."
