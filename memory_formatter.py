from __future__ import annotations

from typing import Any


DEFAULT_ITEM_MAX_CHARS = 360
MAX_EXTRACT_DEPTH = 4
RRF_K = 60


def format_recall_results(
    raw: Any,
    limit: int,
    item_max_chars: int = DEFAULT_ITEM_MAX_CHARS,
    max_extract_depth: int = MAX_EXTRACT_DEPTH,
) -> str:
    memories = extract_memories(raw)
    if not memories:
        return ""

    lines: list[str] = []
    for memory in memories[: max(0, limit)]:
        text = _extract_text(memory, max_depth=max_extract_depth)
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


def extract_memory_texts(raw: Any, limit: int = 0, max_extract_depth: int = MAX_EXTRACT_DEPTH) -> list[str]:
    memories = extract_memories(raw)
    if limit > 0:
        memories = memories[:limit]
    texts: list[str] = []
    for memory in memories:
        text = _extract_text(memory, max_depth=max_extract_depth)
        if text:
            texts.append(_normalize_text(text))
    return texts


def merge_ranked_memories(
    ranked_lists: list[list[Any]],
    max_extract_depth: int = MAX_EXTRACT_DEPTH,
    rrf_k: int = RRF_K,
) -> list[Any]:
    """Merge several ranked recall result lists with reciprocal rank fusion.

    Each list comes from one (scope, query) recall. Concatenating them would let
    the first list fill the whole injection budget; RRF instead favors memories
    ranked high in any list and memories returned by several queries.
    """
    scores: dict[str, float] = {}
    first_seen: dict[str, tuple[int, Any]] = {}
    order = 0
    for memories in ranked_lists:
        seen_in_list: set[str] = set()
        for rank, memory in enumerate(memories):
            text = _extract_text(memory, max_depth=max_extract_depth)
            key = _normalize_text(text).lower()
            if not key or key in seen_in_list:
                continue
            seen_in_list.add(key)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
            if key not in first_seen:
                first_seen[key] = (order, memory)
                order += 1
    ranked_keys = sorted(scores, key=lambda key: (-scores[key], first_seen[key][0]))
    return [first_seen[key][1] for key in ranked_keys]


def _extract_text(
    memory: Any,
    depth: int = 0,
    seen: set[int] | None = None,
    max_depth: int = MAX_EXTRACT_DEPTH,
) -> str:
    if depth > max_depth:
        return ""
    if isinstance(memory, str):
        return memory
    if not isinstance(memory, dict):
        return ""

    if seen is None:
        seen = set()
    memory_id = id(memory)
    if memory_id in seen:
        return ""
    seen.add(memory_id)

    for key in ("text", "content", "memory", "fact", "summary"):
        value = memory.get(key)
        if isinstance(value, str) and value.strip():
            return value

    nested = memory.get("memory")
    if isinstance(nested, dict):
        text = _extract_text(nested, depth + 1, seen, max_depth)
        if text:
            return text

    observation = memory.get("observation")
    if isinstance(observation, dict):
        text = _extract_text(observation, depth + 1, seen, max_depth)
        if text:
            return text

    return ""


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return "." * max_chars
    return text[: max_chars - 3].rstrip() + "..."
