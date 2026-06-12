"""In-process cache for throttled destination index-name verification scans."""

import threading
import time
from dataclasses import dataclass, field


@dataclass
class DestinationScanEntry:
    last_scan_at: float = 0.0
    known_coll_uuids: frozenset = field(default_factory=frozenset)
    extra_built_by_coll: dict = field(default_factory=dict)


_lock = threading.Lock()
_entries: dict[str, DestinationScanEntry] = {}


def coll_uuid_key(coll_uuid):
    """Normalize collUUID values to stable string keys."""
    if isinstance(coll_uuid, bytes):
        return coll_uuid.hex()
    if hasattr(coll_uuid, "__bytes__"):
        return bytes(coll_uuid).hex()
    return str(coll_uuid)


def _get_entry(connection_string):
    entry = _entries.get(connection_string)
    if entry is None:
        entry = DestinationScanEntry()
        _entries[connection_string] = entry
    return entry


def clear_all():
    """Clear all cached entries (for tests)."""
    with _lock:
        _entries.clear()


def scan_is_due(entry, refresh_sec, current_coll_uuids, now):
    if entry.last_scan_at <= 0:
        return True
    if current_coll_uuids != entry.known_coll_uuids:
        return True
    return (now - entry.last_scan_at) >= refresh_sec


def resolve_extra_built_with_cache(
    connection_string,
    groups,
    refresh_sec,
    compute_extra_built,
    now=None,
):
    """
    Return extra_built_by_coll keyed by group collUUID (_id from aggregate).

    Runs compute_extra_built() when the refresh interval elapsed or collection
    set changed; otherwise returns the cached per-collection verified counts.
    """
    if now is None:
        now = time.monotonic()

    pending_groups = [g for g in groups if (g.get("indexesPending") or 0) > 0]
    if not pending_groups:
        with _lock:
            entry = _get_entry(connection_string)
            entry.extra_built_by_coll = {}
            entry.known_coll_uuids = frozenset(
                coll_uuid_key(g["_id"]) for g in groups
            )
            entry.last_scan_at = now
        return {}

    current_coll_uuids = frozenset(coll_uuid_key(g["_id"]) for g in groups)

    with _lock:
        entry = _get_entry(connection_string)
        due = scan_is_due(entry, refresh_sec, current_coll_uuids, now)

    if due:
        extra = compute_extra_built() or {}
        extra_hex = {coll_uuid_key(coll_uuid): count for coll_uuid, count in extra.items()}
        with _lock:
            entry = _get_entry(connection_string)
            entry.last_scan_at = now
            entry.known_coll_uuids = current_coll_uuids
            entry.extra_built_by_coll = extra_hex
        return extra

    with _lock:
        cached = dict(_get_entry(connection_string).extra_built_by_coll)

    result = {}
    for group in pending_groups:
        coll_uuid = group["_id"]
        count = cached.get(coll_uuid_key(coll_uuid))
        if count:
            result[coll_uuid] = count
    return result
