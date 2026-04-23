"""
SQLite-backed log document store with FTS5 full-text search.

Stores raw JSON log lines as documents and provides a MongoDB-like
query API for searching across the full log file. Uses SQLite's
JSON functions for field extraction and FTS5 for full-text search
on the message field.
"""
import json
import logging
import os
import sqlite3
import time
import glob
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LogStore:
    """Document store for mongosync log lines backed by SQLite + FTS5."""

    BATCH_SIZE = 5000

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._pending: list[tuple] = []
        self._total_inserted = 0
        self._open()

    def _open(self):
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA synchronous=OFF")
        self._conn.execute("PRAGMA cache_size=-64000")  # 64 MB cache
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS log_lines (
                rowid INTEGER PRIMARY KEY,
                timestamp TEXT,
                level TEXT,
                message TEXT,
                doc TEXT
            )
        """)
        self._conn.commit()

    def insert_many(self, documents: list[dict]):
        """
        Batch-insert raw JSON documents.

        Each document should be a parsed JSON dict from a log line.
        The raw JSON string is stored in the `doc` column.
        """
        if not documents:
            return
        rows = []
        for doc in documents:
            rows.append((
                doc.get('time', ''),
                doc.get('level', ''),
                doc.get('message', ''),
                json.dumps(doc, separators=(',', ':'))
            ))
        self._conn.executemany(
            "INSERT INTO log_lines(timestamp, level, message, doc) VALUES (?,?,?,?)",
            rows
        )
        self._conn.commit()
        self._total_inserted += len(rows)

    def insert_line(self, line: str, parsed: Optional[dict] = None):
        """
        Buffer a single log line for batched insertion.

        Call flush() after the parsing loop to write remaining buffered rows.
        If `parsed` is provided it is used to extract fields; otherwise
        the raw line string is stored with empty metadata.
        """
        if parsed is not None:
            self._pending.append((
                parsed.get('time', ''),
                parsed.get('level', ''),
                parsed.get('message', ''),
                line
            ))
        else:
            self._pending.append(('', '', '', line))

        if len(self._pending) >= self.BATCH_SIZE:
            self._flush_pending()

    def _flush_pending(self):
        if not self._pending:
            return
        self._conn.executemany(
            "INSERT INTO log_lines(timestamp, level, message, doc) VALUES (?,?,?,?)",
            self._pending
        )
        self._conn.commit()
        self._total_inserted += len(self._pending)
        self._pending.clear()

    def flush(self):
        """Flush any remaining buffered rows to the database."""
        self._flush_pending()

    def build_fts_index(self):
        """
        Build the FTS5 full-text index on the message column.

        Call this once after all inserts are complete for best performance.
        """
        self.flush()
        logger.info(f"Building FTS5 index over {self._total_inserted} log lines...")
        t0 = time.time()
        self._conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS log_fts
            USING fts5(message, content=log_lines, content_rowid=rowid)
        """)
        self._conn.execute("""
            INSERT INTO log_fts(log_fts) VALUES('rebuild')
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_level ON log_lines(level)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON log_lines(timestamp)")
        self._conn.commit()
        elapsed = time.time() - t0
        logger.info(f"FTS5 index built in {elapsed:.2f}s for {self._total_inserted} documents")

    def find(self, query: Optional[dict] = None, skip: int = 0, limit: int = 50) -> dict:
        """
        Query log documents with optional filters.

        Args:
            query: MongoDB-style query dict. Supported keys:
                - "level": exact match (str) or {"$in": [...]} for multiple levels
                - "$text": FTS5 full-text search on message field
                - "timestamp_gte": lines at or after this timestamp
                - "timestamp_lte": lines at or before this timestamp
            skip: number of results to skip (for pagination)
            limit: max results to return (capped at 200)

        Returns:
            dict with keys: results (list of dicts), total (int), skip, limit
        """
        if query is None:
            query = {}
        limit = min(limit, 200)

        conditions = []
        params: list[Any] = []
        use_fts = False
        fts_term = ''

        level_filter = query.get('level')
        if level_filter:
            if isinstance(level_filter, dict) and '$in' in level_filter:
                placeholders = ','.join('?' for _ in level_filter['$in'])
                conditions.append(f"l.level IN ({placeholders})")
                params.extend(level_filter['$in'])
            elif isinstance(level_filter, str) and level_filter:
                conditions.append("l.level = ?")
                params.append(level_filter)

        text_query = query.get('$text', '').strip()
        if text_query:
            use_fts = True
            fts_term = text_query

        ts_gte = query.get('timestamp_gte')
        if ts_gte:
            conditions.append("l.timestamp >= ?")
            params.append(ts_gte)

        ts_lte = query.get('timestamp_lte')
        if ts_lte:
            conditions.append("l.timestamp <= ?")
            params.append(ts_lte)

        where_clause = (" AND ".join(conditions)) if conditions else "1=1"

        if use_fts:
            count_sql = f"""
                SELECT COUNT(*) FROM log_lines l
                JOIN log_fts f ON l.rowid = f.rowid
                WHERE log_fts MATCH ? AND {where_clause}
            """
            data_sql = f"""
                SELECT l.rowid, l.timestamp, l.level, l.message, l.doc
                FROM log_lines l
                JOIN log_fts f ON l.rowid = f.rowid
                WHERE log_fts MATCH ? AND {where_clause}
                ORDER BY l.rowid
                LIMIT ? OFFSET ?
            """
            count_params = [fts_term] + params
            data_params = [fts_term] + params + [limit, skip]
        else:
            count_sql = f"SELECT COUNT(*) FROM log_lines l WHERE {where_clause}"
            data_sql = f"""
                SELECT l.rowid, l.timestamp, l.level, l.message, l.doc
                FROM log_lines l WHERE {where_clause}
                ORDER BY l.rowid
                LIMIT ? OFFSET ?
            """
            count_params = params
            data_params = params + [limit, skip]

        total = self._conn.execute(count_sql, count_params).fetchone()[0]
        rows = self._conn.execute(data_sql, data_params).fetchall()

        results = []
        for row in rows:
            results.append({
                'line': row[0],
                'timestamp': row[1],
                'level': row[2],
                'message': row[3],
                'raw': row[4]
            })

        return {
            'results': results,
            'total': total,
            'skip': skip,
            'limit': limit
        }

    def count(self, query: Optional[dict] = None) -> int:
        """Return the count of matching documents."""
        result = self.find(query, skip=0, limit=1)
        return result['total']

    @property
    def total_documents(self) -> int:
        """Total number of documents in the store."""
        row = self._conn.execute("SELECT COUNT(*) FROM log_lines").fetchone()
        return row[0] if row else 0

    def close(self):
        """Close the database connection."""
        if self._conn:
            self.flush()
            self._conn.close()
            self._conn = None

    def delete(self):
        """Close connection and delete the database file."""
        self.close()
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
                logger.info(f"Deleted log store: {self.db_path}")
                wal = self.db_path + '-wal'
                shm = self.db_path + '-shm'
                for f in (wal, shm):
                    if os.path.exists(f):
                        os.remove(f)
        except OSError as e:
            logger.warning(f"Failed to delete log store {self.db_path}: {e}")

    @staticmethod
    def cleanup_old_stores(store_dir: str, max_age_hours: int = 24):
        """
        Delete log store DB files older than max_age_hours.

        Scans the given directory for files matching mi_logstore_*.db,
        removing those that exceed the age threshold. Snapshot JSON cleanup
        is handled separately by cleanup_old_snapshots() in snapshot_store.
        """
        cutoff = time.time() - (max_age_hours * 3600)
        removed = 0
        pattern = os.path.join(store_dir, 'mi_logstore_*.db')

        for filepath in glob.glob(pattern):
            try:
                if os.path.getmtime(filepath) < cutoff:
                    os.remove(filepath)
                    for suffix in ('-wal', '-shm'):
                        extra = filepath + suffix
                        if os.path.exists(extra):
                            os.remove(extra)
                    removed += 1
            except OSError as e:
                logger.warning(f"Failed to clean up {filepath}: {e}")

        if removed:
            logger.info(f"Cleaned up {removed} expired log store file(s) from {store_dir}")
