"""
Centralized cleanup for log store SQLite files, snapshots, and registry entries.
"""
from .app_config import LOG_STORE_DIR, LOG_STORE_MAX_AGE_HOURS
from .log_store import LogStore
from .log_store_registry import log_store_registry
from .snapshot_store import cleanup_old_snapshots


def run_log_store_maintenance() -> None:
    """Expire registry entries, then remove old on-disk stores and snapshots."""
    log_store_registry.cleanup_expired()
    LogStore.cleanup_old_stores(LOG_STORE_DIR, LOG_STORE_MAX_AGE_HOURS)
    cleanup_old_snapshots(LOG_STORE_DIR, LOG_STORE_MAX_AGE_HOURS)
