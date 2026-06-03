from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


HASH_LENGTH = 16


@dataclass(frozen=True)
class MemoryScope:
    scope_type: str
    platform_id: str
    umo_hash: str
    tags: list[str]
    scope_key: str
    metadata: dict[str, Any]


def build_scope_from_event(event: Any, salt: str) -> MemoryScope:
    platform_id = _sanitize_tag_value(_event_value(event, "get_platform_name", "platform_id") or "unknown")
    umo = str(getattr(event, "unified_msg_origin", "") or "")
    umo_hash = hash_identifier(salt, "umo", umo or "unknown")

    group_id = _event_value(event, "get_group_id", "group_id")
    if group_id:
        group_hash = hash_identifier(salt, "group", str(group_id))
        tags = [
            "scope:group",
            f"platform:{platform_id}",
            f"group:{group_hash}",
            f"umo:{umo_hash}",
        ]
        scope_key = f"group:{platform_id}:{group_hash}:{umo_hash}"
        return MemoryScope(
            scope_type="group",
            platform_id=platform_id,
            umo_hash=umo_hash,
            tags=tags,
            scope_key=scope_key,
            metadata=_metadata("group", platform_id, scope_key),
        )

    sender_id = _event_value(event, "get_sender_id", "sender_id") or _nested_value(
        event, ("message_obj", "sender", "user_id")
    )
    sender_hash = hash_identifier(salt, "sender", str(sender_id or umo or "unknown"))
    tags = [
        "scope:private",
        f"platform:{platform_id}",
        f"sender:{sender_hash}",
        f"umo:{umo_hash}",
    ]
    scope_key = f"private:{platform_id}:{sender_hash}:{umo_hash}"
    return MemoryScope(
        scope_type="private",
        platform_id=platform_id,
        umo_hash=umo_hash,
        tags=tags,
        scope_key=scope_key,
        metadata=_metadata("private", platform_id, scope_key),
    )


def hash_identifier(salt: str, namespace: str, value: str) -> str:
    data = f"{salt}:{namespace}:{value}".encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:HASH_LENGTH]


def _metadata(scope_type: str, platform_id: str, scope_key: str) -> dict[str, Any]:
    return {
        "source": "astrbot_plugin_hindsight_memory",
        "scope": scope_type,
        "platform_id": platform_id,
        "scope_key": scope_key,
    }


def _event_value(event: Any, method_name: str, attr_name: str) -> str | None:
    method = getattr(event, method_name, None)
    if callable(method):
        try:
            value = method()
        except Exception:
            value = None
        if value not in (None, ""):
            return str(value)

    value = getattr(event, attr_name, None)
    if value not in (None, ""):
        return str(value)
    return None


def _nested_value(obj: Any, path: tuple[str, ...]) -> str | None:
    current = obj
    for part in path:
        current = getattr(current, part, None)
        if current is None:
            return None
    if current in (None, ""):
        return None
    return str(current)


def _sanitize_tag_value(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    return normalized.strip("_") or "unknown"
