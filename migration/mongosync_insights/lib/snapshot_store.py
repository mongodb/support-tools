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


def _snapshot_meta_path(snapshot_id: str) -> str:
    return os.path.join(LOG_STORE_DIR, f'{_SNAPSHOT_PREFIX}{snapshot_id}.meta.json')


def _is_main_snapshot_basename(basename: str) -> bool:
    """True for mi_snapshot_<id>.json but not mi_snapshot_<id>.meta.json."""
    return (
        basename.startswith(_SNAPSHOT_PREFIX)
        and basename.endswith('.json')
        and not basename.endswith('.meta.json')
    )


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
    meta_path = _snapshot_meta_path(snapshot_id)
    meta_payload = {k: v for k, v in payload.items() if k != 'template_data'}
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta_payload, f, separators=(',', ':'))
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

    meta_path = _snapshot_meta_path(snapshot_id)
    if os.path.exists(meta_path):
        try:
            os.utime(meta_path, None)
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


def _append_snapshot_row(
    results: list[dict],
    seen_ids: set[str],
    mtime: float,
    data: dict,
    sid_from_file: str,
) -> None:
    age_hours = (time.time() - mtime) / 3600
    if age_hours > LOG_STORE_MAX_AGE_HOURS:
        return
    snapshot_id = data.get('snapshot_id', sid_from_file)
    if not snapshot_id or snapshot_id in seen_ids:
        return
    seen_ids.add(snapshot_id)
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


def list_snapshots() -> list[dict]:
    """
    Scan LOG_STORE_DIR for snapshot metadata sidecars and return listing fields.

    Reads small ``mi_snapshot_<id>.meta.json`` files (no ``template_data``).
    Legacy snapshots with only the main ``.json`` file are listed by parsing
    the full file once.

    Returns a list sorted by mtime descending (most recent first).
    """
    results: list[dict] = []
    seen_ids: set[str] = set()
    meta_pattern = os.path.join(LOG_STORE_DIR, f'{_SNAPSHOT_PREFIX}*.meta.json')

    for filepath in glob.glob(meta_pattern):
        try:
            mtime = os.path.getmtime(filepath)
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            basename = os.path.basename(filepath)
            suffix = basename[len(_SNAPSHOT_PREFIX):-len('.meta.json')]
            _append_snapshot_row(results, seen_ids, mtime, data, suffix)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Skipping unreadable snapshot meta {filepath}: {e}")
            continue

    main_pattern = os.path.join(LOG_STORE_DIR, f'{_SNAPSHOT_PREFIX}*.json')
    for filepath in glob.glob(main_pattern):
        basename = os.path.basename(filepath)
        if not _is_main_snapshot_basename(basename):
            continue
        sid = basename[len(_SNAPSHOT_PREFIX):-len('.json')]
        if os.path.exists(_snapshot_meta_path(sid)):
            continue
        try:
            mtime = os.path.getmtime(filepath)
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _append_snapshot_row(results, seen_ids, mtime, data, sid)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Skipping unreadable legacy snapshot {filepath}: {e}")
            continue

    results.sort(key=lambda x: x.get('mtime', 0), reverse=True)
    for r in results:
        r.pop('mtime', None)
    return results


def delete_snapshot(snapshot_id: str) -> tuple[bool, str]:
    """
    Delete a snapshot JSON file, its metadata sidecar, and its SQLite DB.

    Returns (deleted, log_store_id) where deleted is True if the
    snapshot file was found and removed.
    """
    path = _snapshot_path(snapshot_id)
    meta_path = _snapshot_meta_path(snapshot_id)
    deleted = False
    store_id = ''

    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            store_id = meta.get('log_store_id', '') or store_id
        except (json.JSONDecodeError, OSError):
            pass

    if os.path.exists(path):
        if not store_id:
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

        if os.path.exists(meta_path):
            try:
                os.remove(meta_path)
            except OSError as e:
                logger.warning(f"Failed to delete snapshot meta {meta_path}: {e}")

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

    Skips ``*.meta.json`` (the glob ``mi_snapshot_*.json`` would otherwise
    match those). Removes the sibling ``.meta.json`` when deleting a main file.

    Parallels LogStore.cleanup_old_stores for snapshot files.
    """
    cutoff = time.time() - (max_age_hours * 3600)
    pattern = os.path.join(store_dir, f'{_SNAPSHOT_PREFIX}*.json')
    removed = 0
    for filepath in glob.glob(pattern):
        basename = os.path.basename(filepath)
        if not _is_main_snapshot_basename(basename):
            continue
        try:
            if os.path.getmtime(filepath) < cutoff:
                sid = basename[len(_SNAPSHOT_PREFIX):-len('.json')]
                meta_file = os.path.join(store_dir, f'{_SNAPSHOT_PREFIX}{sid}.meta.json')
                os.remove(filepath)
                removed += 1
                if os.path.exists(meta_file):
                    try:
                        os.remove(meta_file)
                    except OSError as e:
                        logger.warning(f"Failed to clean up snapshot meta {meta_file}: {e}")
        except OSError as e:
            logger.warning(f"Failed to clean up snapshot {filepath}: {e}")
    if removed:
        logger.info(f"Cleaned up {removed} expired snapshot(s) from {store_dir}")
