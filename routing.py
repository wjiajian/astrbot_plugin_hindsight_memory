"""Route Hindsight reads and writes without changing AstrBot's existing scope keys."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from .scope import MemoryScope, MemoryScopes

# Adapters whose sender identity is self-asserted rather than platform-verified.
SELF_ASSERTED_PLATFORMS = frozenset({"webchat"})


@dataclass(frozen=True)
class MemoryRoute:
    primary: MemoryScope
    read_targets: tuple[tuple[str, tuple[str, ...]], ...]
    write_bank: str
    write_scopes: tuple[MemoryScope, ...]
    mode_key: str | None
    private_mode: bool | None = None


def bank_ids(config: Mapping[str, Any]) -> tuple[str, str]:
    return (str(config.get("bank_id") or "").strip(), str(config.get("shared_bank_id") or "").strip())


def _ids(raw: object) -> set[str]:
    if isinstance(raw, str):
        raw = raw.replace("，", ",").split(",")
    if not isinstance(raw, (list, tuple, set)):
        return set()
    return {str(item).strip() for item in raw if item is not None and str(item).strip()}


def owner_mode_key(event: Any, scopes: MemoryScopes, config: Mapping[str, Any], global_admins: object) -> str | None:
    base, shared = bank_ids(config)
    if not base or not shared or base == shared or scopes.primary.scope_type != "private":
        return None
    owner_platform = str(config.get("owner_platform_id") or "").strip()
    if not owner_platform:
        return None
    try:
        if str(event.get_platform_name() or "") in SELF_ASSERTED_PLATFORMS:
            return None
        if event.is_private_chat() is not True or event.get_platform_id() != owner_platform:
            return None
        sender = str(event.get_sender_id() or "").strip()
        if not sender:
            return None
        owners = _ids(config.get("owner_user_ids"))
        allowed = sender in owners if owners else (sender in _ids(global_admins) or event.is_admin() is True)
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return None
    if not allowed:
        return None
    # Keep the private-mode marker from the initial PR, but retain the normal
    # scope key for the existing /hindsight on and off commands.
    scope = scopes.primary
    return f"owner-private:{scope.platform_id}:{scope.umo_hash}"


def plan_memory_route(
    scopes: MemoryScopes, config: Mapping[str, Any], mode_key: str | None, private_mode: bool | None,
) -> MemoryRoute:
    base, shared = bank_ids(config)
    local_reads = tuple((base, tuple(scope.tags)) for scope in scopes.recall_scopes)
    local_writes = tuple(scopes.retain_scopes)
    if not mode_key or not base or not shared or base == shared:
        return MemoryRoute(scopes.primary, local_reads, base, local_writes, None, private_mode)
    if private_mode is None:  # Unreadable state is not permission to use the shared bank.
        return MemoryRoute(scopes.primary, local_reads, base, local_writes, mode_key, None)
    shared_reads = ((shared, ()),)
    if private_mode:
        return MemoryRoute(scopes.primary, local_reads + shared_reads, base, local_writes, mode_key, True)
    shared_scope = replace(scopes.primary, tags=[], metadata={"source": "astrbot-private-owner", "scope": "private"})
    return MemoryRoute(scopes.primary, shared_reads, shared, (shared_scope,), mode_key, False)
