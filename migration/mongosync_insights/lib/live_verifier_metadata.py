"""Read embedded verifier progress from mongosync verifier persistence on the destination cluster.

Requires mongosync to run with verifier persistence enabled (enableVerifierPersistence).
This is not the migration-verifier lab tool database.
"""

import logging

from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

VERIFIER_CV_COLLECTION = "collection_verification"
VERIFIER_CHECKSUM_COLLECTION = "collection_checksum"

_PHASE_NOT_STARTED = "not started"
_PHASE_INITIAL_HASHING = "initial hashing"
_PHASE_STREAM_HASHING = "stream hashing"

_ALL_CV_PHASES = (
    _PHASE_NOT_STARTED,
    _PHASE_INITIAL_HASHING,
    _PHASE_STREAM_HASHING,
    "dropped",
    "ignored",
)


def _normalize_phase(raw):
    if not raw:
        return _PHASE_NOT_STARTED
    return str(raw).strip().lower()


def _rollup_cv_phases(cv_docs):
    """Mirror verifier/auditor/progress.go cluster phase rollup from CV documents."""
    if not cv_docs:
        return {
            "phase": _PHASE_NOT_STARTED,
            "scannedCollectionCount": None,
            "totalCollectionCount": None,
        }

    counts = {phase: 0 for phase in _ALL_CV_PHASES}
    for doc in cv_docs:
        phase = _normalize_phase(doc.get("phase"))
        if phase not in counts:
            phase = _PHASE_NOT_STARTED
        counts[phase] += 1

    total = sum(counts.values())
    scanned = counts[_PHASE_STREAM_HASHING]

    if counts[_PHASE_NOT_STARTED] == total:
        reported_phase = _PHASE_NOT_STARTED
    elif counts[_PHASE_STREAM_HASHING] == total:
        reported_phase = _PHASE_STREAM_HASHING
    else:
        reported_phase = _PHASE_INITIAL_HASHING

    return {
        "phase": reported_phase,
        "scannedCollectionCount": scanned,
        "totalCollectionCount": total,
    }


def _sum_checksum_doc_counts(db):
    try:
        pipeline = [
            {"$group": {"_id": None, "total": {"$sum": "$docCount"}}},
        ]
        rows = list(db[VERIFIER_CHECKSUM_COLLECTION].aggregate(pipeline))
    except PyMongoError as e:
        logger.debug("Could not aggregate verifier checksum docCount: %s", e)
        return None

    if not rows:
        return None
    total = rows[0].get("total")
    if total is None:
        return None
    return max(0, int(total))


def _database_has_verifier_data(db):
    try:
        names = db.list_collection_names()
    except PyMongoError:
        return False
    return VERIFIER_CV_COLLECTION in names or VERIFIER_CHECKSUM_COLLECTION in names


def _side_progress_from_persistence(db):
    """Build progress-api side dict from one verifier metadata database, or None if absent."""
    if db is None or not _database_has_verifier_data(db):
        return None

    try:
        cv_docs = list(db[VERIFIER_CV_COLLECTION].find({}))
    except PyMongoError as e:
        logger.debug("Could not read verifier collection_verification: %s", e)
        return None

    rollup = _rollup_cv_phases(cv_docs)
    side = {"phase": rollup["phase"]}

    if rollup["totalCollectionCount"] is not None:
        side["totalCollectionCount"] = rollup["totalCollectionCount"]
    if rollup["scannedCollectionCount"] is not None:
        side["scannedCollectionCount"] = rollup["scannedCollectionCount"]

    hashed = _sum_checksum_doc_counts(db)
    if hashed is not None:
        side["hashedDocumentCount"] = hashed

    return side


def fetch_verifier_persistence_status(connection_string):
    """
    Read verifier persistence from destination cluster internal DBs.

    Returns progress-api-shaped {"source": {...}, "destination": {...}} or None
    when neither side has persistence data.
    """
    from .app_config import VERIFIER_DST_NAMESPACE, VERIFIER_SRC_NAMESPACE, get_database

    if not connection_string:
        return None

    try:
        src_db = get_database(connection_string, VERIFIER_SRC_NAMESPACE)
        dst_db = get_database(connection_string, VERIFIER_DST_NAMESPACE)
    except PyMongoError as e:
        logger.debug("Could not open verifier persistence databases: %s", e)
        return None

    source = _side_progress_from_persistence(src_db)
    destination = _side_progress_from_persistence(dst_db)

    if not source and not destination:
        return None

    result = {}
    if source:
        result["source"] = source
    if destination:
        result["destination"] = destination
    return result or None
