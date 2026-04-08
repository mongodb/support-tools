"""
Global registry mapping log store IDs to their on-disk SQLite paths.

Thread-safe singleton that allows the search endpoint to locate the
correct LogStore database for a given store_id returned to the client.
"""
import logging
import os
import threading
import time
from typing import Optional

from .log_store import LogStore

logger = logging.getLogger(__name__)


class LogStoreRegistry:
    """Thread-safe registry of active LogStore instances."""

    def __init__(self, default_ttl: int = 86400):
        """
        Args:
            default_ttl: seconds before an entry is considered expired (default 24h)
        """
        self._entries: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._ttl = default_ttl

    def register(self, store_id: str, db_path: str):
        """Register a store_id -> db_path mapping."""
        with self._lock:
            self._entries[store_id] = {
                'db_path': db_path,
                'created_at': time.time(),
                'store': None,
            }
        logger.debug(f"Registered log store {store_id[:8]}... -> {db_path}")

    def get_path(self, store_id: str) -> Optional[str]:
        """Get the db_path for a store_id, or None if not found/expired."""
        if not store_id:
            return None
        with self._lock:
            entry = self._entries.get(store_id)
            if not entry:
                return None
            if time.time() - entry['created_at'] > self._ttl:
                self._remove_entry(store_id)
                return None
            return entry['db_path']

    def open_store(self, store_id: str) -> Optional[LogStore]:
        """
        Return a cached LogStore connection for the given store_id.

        Returns None if the store_id is not registered or the DB file
        no longer exists. The returned LogStore is owned by the registry;
        callers must NOT close it.
        """
        with self._lock:
            entry = self._entries.get(store_id)
            if not entry:
                return None
            if time.time() - entry['created_at'] > self._ttl:
                self._remove_entry(store_id)
                return None
            db_path = entry['db_path']
            if not os.path.exists(db_path):
                return None
            if entry['store'] is None:
                entry['store'] = LogStore(db_path)
            return entry['store']

    def remove(self, store_id: str):
        """Remove a store entry and delete the DB file from disk."""
        with self._lock:
            self._remove_entry(store_id)

    def _remove_entry(self, store_id: str):
        """Internal: remove entry and delete DB file. Caller must hold lock."""
        entry = self._entries.pop(store_id, None)
        if entry:
            cached_store = entry.get('store')
            if cached_store is not None:
                try:
                    cached_store.close()
                except Exception:
                    pass
            db_path = entry['db_path']
            try:
                if os.path.exists(db_path):
                    os.remove(db_path)
                for suffix in ('-wal', '-shm'):
                    extra = db_path + suffix
                    if os.path.exists(extra):
                        os.remove(extra)
                logger.debug(f"Removed log store {store_id[:8]}... ({db_path})")
            except OSError as e:
                logger.warning(f"Failed to delete log store file {db_path}: {e}")

    def cleanup_expired(self):
        """Remove all entries that have exceeded their TTL."""
        now = time.time()
        with self._lock:
            expired = [
                sid for sid, entry in self._entries.items()
                if now - entry['created_at'] > self._ttl
            ]
            for sid in expired:
                self._remove_entry(sid)
            if expired:
                logger.info(f"Cleaned up {len(expired)} expired log store(s)")

    def remove_all(self):
        """Remove all registered stores (used during shutdown)."""
        with self._lock:
            for sid in list(self._entries.keys()):
                self._remove_entry(sid)

    def count(self) -> int:
        """Number of currently registered stores."""
        with self._lock:
            return len(self._entries)


log_store_registry = LogStoreRegistry()
