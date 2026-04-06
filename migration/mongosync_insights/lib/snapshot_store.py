"""
Snapshot persistence for parsed log analysis results.

Saves all template data (Plotly figures, tables, log viewer lines) as a
JSON file on disk so that a previous analysis can be reloaded instantly
without re-parsing the original log file. Each snapshot references its
companion SQLite log store DB for full-text search.
"""
import glob
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from .app_config import LOG_STORE_DIR, LOG_STORE_MAX_AGE_HOURS

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1
_SNAPSHOT_PREFIX = 'mi_snapshot_'
_LOGSTORE_PREFIX = 'mi_logstore_'


def _snapshot_path(snapshot_id: str) -> str:
    return os.path.join(LOG_STORE_DIR, f'{_SNAPSHOT_PREFIX}{snapshot_id}.json')


def logstore_path(store_id: str) -> str:
    return os.path.join(LOG_STORE_DIR, f'{_LOGSTORE_PREFIX}{store_id}.db')


def save_snapshot(
    snapshot_id: str,
    source_filename: str,
    source_size: int,
    line_count: int,
    log_store_id: str,
    template_data: dict[str, Any],
) -> str:
    """
    Save all parsed analysis data to a JSON file on disk.

    Returns the file path of the saved snapshot.
    """
    path = _snapshot_path(snapshot_id)
    payload = {
        'version': SNAPSHOT_VERSION,
        'snapshot_id': snapshot_id,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'source_filename': source_filename,
        'source_size_bytes': source_size,
        'line_count': line_count,
        'log_store_id': log_store_id,
        'template_data': template_data,
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, separators=(',', ':'))
    logger.info(f"Saved snapshot {snapshot_id[:8]}... for '{source_filename}' ({line_count} lines)")
    return path


def load_snapshot(snapshot_id: str) -> Optional[dict]:
    """
    Load a snapshot from disk and refresh its TTL.

    Touches the mtime of both the snapshot JSON and its companion SQLite
    DB so that age-based cleanup is postponed by another TTL cycle.

    Returns the full snapshot dict (including template_data) or None.
    """
    path = _snapshot_path(snapshot_id)
    if not os.path.exists(path):
        logger.warning(f"Snapshot not found: {path}")
        return None

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load snapshot {snapshot_id[:8]}...: {e}")
        return None

    # Refresh mtime on snapshot file
    try:
        os.utime(path, None)
    except OSError:
        pass

    # Refresh mtime on companion SQLite DB if it exists
    store_id = data.get('log_store_id', '')
    if store_id:
        db_path = logstore_path(store_id)
        try:
            if os.path.exists(db_path):
                os.utime(db_path, None)
        except OSError:
            pass

    logger.info(f"Loaded snapshot {snapshot_id[:8]}... ('{data.get('source_filename', '?')}')")
    return data


def list_snapshots() -> list[dict]:
    """
    Scan LOG_STORE_DIR for snapshot files and return metadata.

    Returns a list sorted by mtime descending (most recent first).
    Only reads the top-level metadata fields, not the full template_data.
    """
    pattern = os.path.join(LOG_STORE_DIR, f'{_SNAPSHOT_PREFIX}*.json')
    results = []

    for filepath in glob.glob(pattern):
        try:
            mtime = os.path.getmtime(filepath)
            age_hours = (time.time() - mtime) / 3600

            if age_hours > LOG_STORE_MAX_AGE_HOURS:
                continue

            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)

            basename = os.path.basename(filepath)
            sid = basename.replace(_SNAPSHOT_PREFIX, '').replace('.json', '')
            snapshot_id = data.get('snapshot_id', sid)
            if not snapshot_id:
                continue

            results.append({
                'snapshot_id': snapshot_id,
                'source_filename': data.get('source_filename', 'Unknown'),
                'created_at': data.get('created_at', ''),
                'source_size_bytes': data.get('source_size_bytes', 0),
                'line_count': data.get('line_count', 0),
                'log_store_id': data.get('log_store_id', ''),
                'age_hours': round(age_hours, 1),
                'mtime': mtime,
            })
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.warning(f"Skipping unreadable snapshot {filepath}: {e}")
            continue

    results.sort(key=lambda x: x.get('mtime', 0), reverse=True)
    for r in results:
        r.pop('mtime', None)
    return results


def delete_snapshot(snapshot_id: str) -> tuple[bool, str]:
    """
    Delete a snapshot JSON file and its associated SQLite DB.

    Returns (deleted, log_store_id) where deleted is True if the
    snapshot file was found and removed.
    """
    path = _snapshot_path(snapshot_id)
    deleted = False
    store_id = ''

    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            store_id = data.get('log_store_id', '')
        except (json.JSONDecodeError, OSError):
            pass

        try:
            os.remove(path)
            deleted = True
            logger.info(f"Deleted snapshot {snapshot_id[:8]}...")
        except OSError as e:
            logger.warning(f"Failed to delete snapshot {path}: {e}")

        if store_id:
            db_path = logstore_path(store_id)
            for fpath in (db_path, db_path + '-wal', db_path + '-shm'):
                try:
                    if os.path.exists(fpath):
                        os.remove(fpath)
                except OSError:
                    pass

    return deleted, store_id


def cleanup_old_snapshots(store_dir: str, max_age_hours: int = 24):
    """
    Delete snapshot JSON files older than max_age_hours by mtime.

    Parallels LogStore.cleanup_old_stores for snapshot files.
    """
    cutoff = time.time() - (max_age_hours * 3600)
    pattern = os.path.join(store_dir, f'{_SNAPSHOT_PREFIX}*.json')
    removed = 0
    for filepath in glob.glob(pattern):
        try:
            if os.path.getmtime(filepath) < cutoff:
                os.remove(filepath)
                removed += 1
        except OSError as e:
            logger.warning(f"Failed to clean up snapshot {filepath}: {e}")
    if removed:
        logger.info(f"Cleaned up {removed} expired snapshot(s) from {store_dir}")
