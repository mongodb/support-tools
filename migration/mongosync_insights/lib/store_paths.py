"""
Safe path construction for snapshot and log-store files under LOG_STORE_DIR.

All store IDs are server-generated UUIDs; validate before joining paths.
"""
import os
import re

STORE_ID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def validate_store_id(value: str) -> str:
    """Return value if it is a valid UUID-shaped store/snapshot ID."""
    if not value or not STORE_ID_RE.fullmatch(value):
        raise ValueError(f'Invalid store id: {value!r}')
    return value


def is_valid_store_id(value: str) -> bool:
    """Return True if value is a valid UUID-shaped store/snapshot ID."""
    return bool(value and STORE_ID_RE.fullmatch(value))


def safe_path_under(base_dir: str, *parts: str) -> str:
    """
    Join path parts under base_dir and ensure the result does not escape it.

    Raises ValueError if the resolved path is outside base_dir.
    """
    base = os.path.realpath(base_dir)
    path = os.path.realpath(os.path.join(base, *parts))
    if path != base and not path.startswith(base + os.sep):
        raise ValueError(f'Path escapes store directory: {path!r}')
    return path
