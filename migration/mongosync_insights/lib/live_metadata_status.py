"""Read mongosync internal metadata DB status for Live Monitoring."""

import logging
from datetime import datetime, timezone

from bson import Timestamp
from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)


class MetadataFetchError(Exception):
    """Raised when metadata cannot be read from the internal database."""


def _parse_phase_ts(ts):
    if isinstance(ts, Timestamp):
        return datetime.fromtimestamp(ts.time, tz=timezone.utc)
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    return None


def get_phase_timestamp(phase_transitions, phase_name):
    """Find the first matching phase and return its timestamp as datetime."""
    if not phase_transitions:
        return None
    for pt in phase_transitions:
        if pt.get("phase") == phase_name:
            return _parse_phase_ts(pt.get("ts"))
    return None


def get_phase_transition_series(phase_transitions):
    """Return parallel phase labels and UTC datetimes (matches Progress tab chart)."""
    if not phase_transitions:
        return [], []
    phases = []
    datetimes = []
    for pt in phase_transitions:
        phase_raw = pt.get("phase", "")
        phases.append(phase_raw.capitalize() if phase_raw else "—")
        datetimes.append(_parse_phase_ts(pt.get("ts")))
    return phases, datetimes


def format_phase_transition_rows(phase_transitions):
    """Format phaseTransitions for Live Monitoring display (phase + startedAt strings)."""
    phases, datetimes = get_phase_transition_series(phase_transitions)
    return [
        {
            "phase": phase,
            "startedAt": _format_timestamp(dt) if dt else "—",
        }
        for phase, dt in zip(phases, datetimes)
    ]


def _parse_last_event_ts(last_event_ts):
    if not last_event_ts:
        return None
    if isinstance(last_event_ts, Timestamp):
        return datetime.fromtimestamp(last_event_ts.time, tz=timezone.utc)
    if isinstance(last_event_ts, datetime):
        return (
            last_event_ts
            if last_event_ts.tzinfo
            else last_event_ts.replace(tzinfo=timezone.utc)
        )
    return None


def _get_last_event_datetime(resume_info):
    """Extract lastEventTs from resume info (dict or list of dicts)."""
    if not resume_info:
        return None
    if isinstance(resume_info, list):
        candidates = [
            _parse_last_event_ts(entry.get("lastEventTs"))
            for entry in resume_info
            if isinstance(entry, dict)
        ]
        valid = [dt for dt in candidates if dt is not None]
        return max(valid) if valid else None
    return _parse_last_event_ts(resume_info.get("lastEventTs"))


def compute_lag_time_seconds(resume_data):
    """Lag seconds from change-stream resume timestamps vs UTC now."""
    if not resume_data:
        return None
    crud_dt = _get_last_event_datetime(resume_data.get("crudChangeStreamResumeInfo"))
    ddl_dt = _get_last_event_datetime(resume_data.get("ddlChangeStreamResumeInfo"))
    last_event_dt = None
    if crud_dt and ddl_dt:
        last_event_dt = max(crud_dt, ddl_dt)
    elif crud_dt:
        last_event_dt = crud_dt
    elif ddl_dt:
        last_event_dt = ddl_dt
    if not last_event_dt:
        return None
    lag = datetime.now(tz=timezone.utc) - last_event_dt
    total_seconds = int(lag.total_seconds())
    return max(0, total_seconds)


def format_write_blocking_mode(raw):
    if raw == "destinationOnly":
        return "Destination Only"
    if raw == "sourceAndDestination":
        return "Source and Destination"
    if raw == "none":
        return "None"
    return None


def format_build_indexes(raw):
    if raw == "afterDataCopy":
        return "After Data Copy"
    if raw == "beforeDataCopy":
        return "Before Data Copy"
    if raw == "excludeHashed":
        return "Exclude Hashed (Before Copy)"
    if raw == "excludeHashedAfterCopy":
        return "Exclude Hashed (After Copy)"
    if raw == "never":
        return "Never"
    return None


_BUILD_INDEXES_POLICY_MESSAGES = {
    "afterDataCopy": (
        "Index build will start on the destination after the collection copy."
    ),
    "beforeDataCopy": (
        "Indexes were built on the destination during initialization."
    ),
    "excludeHashed": (
        "Indexes were built on the destination during initialization, "
        "and Hashed indexes were skipped."
    ),
    "excludeHashedAfterCopy": (
        "Index build will start on the destination after the collection copy "
        "and Hashed indexes will be skipped."
    ),
}


def describe_build_indexes_policy(raw):
    """Return an informational message for globalState.buildIndexes, or None if unknown."""
    if not raw:
        return None
    return _BUILD_INDEXES_POLICY_MESSAGES.get(raw)


_AFTER_DATA_COPY_BUILD_POLICIES = frozenset({"afterDataCopy", "excludeHashedAfterCopy"})

_BEFORE_CEA_PHASES = frozenset(
    {
        "uninitialized",
        "initializing collections and indexes",
        "collection copy",
        "waiting to start change event application",
    }
)


def build_indexes_starts_after_data_copy(build_indexes_raw):
    """True when index builds are scheduled after collection copy completes."""
    return build_indexes_raw in _AFTER_DATA_COPY_BUILD_POLICIES


def normalize_sync_phase(sync_phase):
    if not sync_phase:
        return None
    return str(sync_phase).strip().lower()


def is_during_or_after_cea(sync_phase):
    """True once mongosync has reached change event application or a later phase."""
    normalized = normalize_sync_phase(sync_phase)
    if not normalized:
        return False
    return normalized not in _BEFORE_CEA_PHASES


def should_suppress_index_build_progress(build_indexes_raw, sync_phase):
    """Hide after-copy index progress while sync is still before CEA."""
    if not build_indexes_starts_after_data_copy(build_indexes_raw):
        return False
    normalized = normalize_sync_phase(sync_phase)
    if not normalized:
        return False
    return normalized in _BEFORE_CEA_PHASES


def index_build_progress_allowed(build_indexes_raw, sync_phase):
    """True when metadata-backed index progress may be fetched or displayed."""
    if not build_indexes_raw or build_indexes_raw == "never":
        return False
    if build_indexes_starts_after_data_copy(build_indexes_raw):
        return is_during_or_after_cea(sync_phase)
    return True


def verification_progress_allowed(verification_mode_raw, sync_phase):
    """True when metadata-backed verifier progress may be fetched or displayed."""
    if not verification_mode_raw or verification_mode_raw == "disabled":
        return False
    if verification_mode_raw == "startAtCEA":
        return is_during_or_after_cea(sync_phase)
    return True


def describe_verification_mode(raw):
    """Return an informational message for globalState.verificationMode, or None if unknown."""
    canonical = normalize_verification_mode(raw)
    if canonical == "disabled":
        return "The embedded verifier is disabled."
    if canonical == "startAtCEA":
        return "Verification will start at the change event application (CEA) phase."
    return None


def normalize_verification_mode(raw):
    """Map globalState verification mode strings to canonical values."""
    if raw is None or raw == "":
        return None
    key = str(raw).lower().replace("_", "")
    if key == "disabled":
        return "disabled"
    if key == "startatcea":
        return "startAtCEA"
    return str(raw)


def read_verification_mode_from_global_state(global_state):
    """Read verification mode from globalState (camelCase or lowercase key)."""
    if not global_state:
        return None
    raw = global_state.get("verificationMode")
    if raw is None:
        raw = global_state.get("verificationmode")
    return normalize_verification_mode(raw)


def parse_copy_in_natural_order_filter(filter_data):
    """
    Parse globalState.copyInNaturalOrderFilter (matches Live Monitoring - Status tab).

    Returns a list of {database, collections} rows when natural order is active,
    or None when nothing is being copied in natural order.
    """
    if not filter_data:
        return None
    select_all = filter_data.get("selectAll", False)
    dbs_and_colls = filter_data.get("dbsAndColls", {})
    if select_all:
        return [{"database": "All", "collections": "All databases and collections"}]
    if dbs_and_colls:
        rows = []
        for db, colls in dbs_and_colls.items():
            rows.append(
                {
                    "database": db,
                    "collections": ", ".join(colls) if colls else "All collections",
                }
            )
        return rows if rows else None
    return None


def format_namespace_filter_rows(filter_data, filter_type="inclusion"):
    """
    Format namespace filter data for display (matches Live Monitoring - Status tab).

    Returns a list of {key, value} rows.
    """
    if not filter_data:
        if filter_type == "inclusion":
            return [{"key": "Database", "value": "All (no filter)"}]
        return [{"key": "Filter", "value": "No filter"}]

    keys = []
    values = []

    for item in filter_data:
        if not isinstance(item, dict):
            continue
        database = item.get("database")
        if database:
            if isinstance(database, list):
                db_list = []
                for db in database:
                    if isinstance(db, list):
                        db_list.extend(db)
                    else:
                        db_list.append(str(db))
                keys.append("Database")
                values.append(", ".join(db_list) if db_list else "All (no filter)")

        collections = item.get("collections")
        if collections:
            if isinstance(collections, list):
                keys.append("Collections")
                values.append(", ".join([str(c) for c in collections]))
            else:
                keys.append("Collections")
                values.append(str(collections))
        elif collections is None and database:
            keys.append("Collections")
            values.append("All (no filter)")

    if not keys:
        if filter_type == "inclusion":
            return [{"key": "Database", "value": "All (no filter)"}]
        return [{"key": "Filter", "value": "No filter"}]

    return [{"key": k, "value": v} for k, v in zip(keys, values)]


def namespace_filter_is_active(namespace_filter):
    """True when inclusionFilter or exclusionFilter is a non-empty list."""
    if not namespace_filter:
        return False
    inclusion = namespace_filter.get("inclusionFilter")
    exclusion = namespace_filter.get("exclusionFilter")
    return bool(inclusion) or bool(exclusion)


def _format_timestamp(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


_PARTITION_BYTE_TOTALS_PIPELINE = [
    {
        "$group": {
            "_id": None,
            "copiedBytes": {"$sum": "$copiedByteCount"},
            "totalBytes": {"$sum": "$totalByteCount"},
        }
    }
]


def fetch_partition_byte_totals(db):
    """
    Sum copiedByteCount and totalByteCount across the partitions collection.

    Returns:
        tuple[int | None, int | None]: (copiedBytes, totalBytes), or (None, None) if no data.
    """
    rows = list(db.partitions.aggregate(_PARTITION_BYTE_TOTALS_PIPELINE))
    if not rows:
        return None, None
    row = rows[0]
    return row.get("copiedBytes"), row.get("totalBytes")


_COLLECTION_COPY_PIPELINE = [
    {
        "$project": {
            "namespace": {"$concat": ["$namespace.db", ".", "$namespace.coll"]},
            "partitionPhase": 1,
        }
    },
    {"$group": {"_id": "$namespace", "phases": {"$addToSet": "$partitionPhase"}}},
    {
        "$project": {
            "_id": 0,
            "namespace": "$_id",
            "phases": {
                "$arrayToObject": {
                    "$map": {
                        "input": "$phases",
                        "as": "phase",
                        "in": {"k": "$$phase", "v": 1},
                    }
                }
            },
        }
    },
    {
        "$project": {
            "_id": 0,
            "namespace": 1,
            "phases": {
                "$mergeObjects": [
                    {"not started": 0, "in progress": 0, "done": 0},
                    "$phases",
                ]
            },
        }
    },
]


def _classify_collection_phases(collection_rows):
    """Count collections by copy status (matches Live Monitoring - Progress tab)."""
    not_started = 0
    in_progress = 0
    done = 0
    for collec in collection_rows:
        phases = collec.get("phases") or {}
        if (phases.get("in progress") == 1) or (
            phases.get("not started") == 1 and phases.get("done") == 1
        ):
            in_progress += 1
        elif phases.get("not started") == 1 and phases.get("done") != 1:
            not_started += 1
        else:
            done += 1
    return not_started, in_progress, done


def fetch_collection_copy_totals(db):
    """
    Count completed vs total collections from partitions (namespace-level).

    Returns:
        dict with collectionsCopied (Done), collectionsTotal, notStarted, inProgress,
        completed — or None if no collection data.
    """
    collection_rows = list(db.partitions.aggregate(_COLLECTION_COPY_PIPELINE))
    if not collection_rows:
        return None

    not_started, in_progress, done = _classify_collection_phases(collection_rows)
    total = done + in_progress + not_started
    if total == 0:
        return None

    return {
        "collectionsCopied": done,
        "collectionsTotal": total,
        "notStarted": not_started,
        "inProgress": in_progress,
        "completed": done,
    }


def fetch_partition_phase_totals(db):
    """
    Count completed vs total partitions across all collections (document-level).

    Each document in partitions is one partition; completed = partitionPhase \"done\".
    """
    pipeline = [{"$group": {"_id": "$partitionPhase", "count": {"$sum": 1}}}]
    rows = list(db.partitions.aggregate(pipeline))
    if not rows:
        return None

    counts = {row["_id"]: row["count"] for row in rows if row.get("_id") is not None}
    done = counts.get("done", 0)
    not_started = counts.get("not started", 0)
    in_progress = counts.get("in progress", 0)
    total = done + not_started + in_progress
    if total == 0:
        return None

    return {
        "partitionsCopied": done,
        "partitionsTotal": total,
    }


_INDEX_CORRECTION_BY_COLLECTION_PIPELINE = [
    {
        "$group": {
            "_id": "$_id.collUUID",
            "indexesTotal": {"$sum": 1},
            "indexesPending": {
                "$sum": {
                    "$cond": [
                        {
                            "$ne": [
                                "$shouldCorrectCounter",
                                "$lastCorrectedCounter",
                            ]
                        },
                        1,
                        0,
                    ]
                }
            },
        }
    },
]


_INDEX_CORRECTION_PENDING_FILTER = {
    "$expr": {"$ne": ["$shouldCorrectCounter", "$lastCorrectedCounter"]}
}


def _fetch_destination_index_names(connection_string, db_name, coll_name):
    """Return index names on a destination collection, or None if unavailable."""
    from .app_config import get_database

    try:
        user_db = get_database(connection_string, db_name)
        return {
            idx.get("name")
            for idx in user_db[coll_name].list_indexes()
            if idx.get("name")
        }
    except PyMongoError as exc:
        logger.debug(
            "list_indexes failed for %s.%s: %s",
            db_name,
            coll_name,
            exc,
        )
        return None


def _scan_destination_verified_built_by_collection(internal_db, connection_string, groups):
    """
    Count counter-pending indexes that already exist on the destination by name.

    Only collections with counter-pending indexes are scanned.
    """
    pending_groups = [g for g in groups if (g.get("indexesPending") or 0) > 0]
    if not pending_groups:
        return {}

    pending_docs = list(
        internal_db.indexCorrection.find(_INDEX_CORRECTION_PENDING_FILTER, {"_id": 1})
    )
    if not pending_docs:
        return {}

    pending_by_coll = {}
    for doc in pending_docs:
        key = doc.get("_id") or {}
        coll_uuid = key.get("collUUID")
        index_name = key.get("indexName")
        if coll_uuid is None or not index_name:
            continue
        pending_by_coll.setdefault(coll_uuid, []).append(index_name)

    if not pending_by_coll:
        return {}

    coll_uuids = list(pending_by_coll.keys())
    uuid_maps = {
        doc["_id"]: doc
        for doc in internal_db.uuidMap.find({"_id": {"$in": coll_uuids}})
    }

    dest_cache = {}
    extra_built_by_coll = {}

    for coll_uuid, index_names in pending_by_coll.items():
        mapping = uuid_maps.get(coll_uuid)
        if not mapping:
            continue
        db_name = mapping.get("dbName")
        coll_name = mapping.get("dstCollName")
        if not db_name or not coll_name:
            continue

        cache_key = (db_name, coll_name)
        if cache_key not in dest_cache:
            dest_cache[cache_key] = _fetch_destination_index_names(
                connection_string, db_name, coll_name
            )
        dest_names = dest_cache[cache_key]
        if dest_names is None:
            continue

        extra_built = sum(1 for name in index_names if name in dest_names)
        if extra_built:
            extra_built_by_coll[coll_uuid] = extra_built

    return extra_built_by_coll


def _apply_destination_verified_built(groups, extra_built_by_coll):
    """Reduce pending counts for indexes verified on the destination."""
    if not extra_built_by_coll:
        return groups

    adjusted = []
    for group in groups:
        coll_uuid = group["_id"]
        extra = extra_built_by_coll.get(coll_uuid, 0)
        if not extra:
            adjusted.append(group)
            continue
        adjusted.append(
            {
                **group,
                "indexesPending": max(0, (group.get("indexesPending") or 0) - extra),
            }
        )
    return adjusted


def _rollup_index_correction_groups(groups):
    """
    Roll up per-collection indexCorrection counter groups into progress totals.

    An index is pending when shouldCorrectCounter != lastCorrectedCounter,
    matching mongosync ICS GetIndexesToCheck semantics.
    """
    if not groups:
        return None

    collections_total = len(groups)
    indexes_total = sum(group.get("indexesTotal") or 0 for group in groups)
    indexes_pending = sum(group.get("indexesPending") or 0 for group in groups)

    if collections_total <= 0 or indexes_total <= 0:
        return None

    collections_finished = sum(
        1 for group in groups if (group.get("indexesPending") or 0) == 0
    )

    return {
        "collectionsTotal": int(collections_total),
        "indexesTotal": int(indexes_total),
        "indexesBuilt": int(indexes_total - indexes_pending),
        "collectionsFinished": int(collections_finished),
    }


def fetch_index_correction_status(internal_db, connection_string=None, *, refresh_sec=60):
    """
    Index building totals and progress from indexCorrection counter fields.

    Progress uses counter equality (shouldCorrectCounter == lastCorrectedCounter)
    and, when a connection string is available, treats counter-pending indexes
    that already exist on the destination as built (ICS DoneCreate semantics).
    Destination name checks are throttled by refresh_sec.

    Returns:
        dict with collectionsTotal, indexesTotal, indexesBuilt, collectionsFinished,
        or None if no indexCorrection data.
    """
    from .index_build_destination_cache import resolve_extra_built_with_cache

    groups = list(
        internal_db.indexCorrection.aggregate(_INDEX_CORRECTION_BY_COLLECTION_PIPELINE)
    )
    if not groups:
        return None

    extra_built_by_coll = {}
    if connection_string:
        extra_built_by_coll = resolve_extra_built_with_cache(
            connection_string,
            groups,
            refresh_sec,
            lambda: _scan_destination_verified_built_by_collection(
                internal_db, connection_string, groups
            ),
        )

    adjusted_groups = _apply_destination_verified_built(groups, extra_built_by_coll)
    return _rollup_index_correction_groups(adjusted_groups)


def fetch_metadata_status(
    connection_string,
    *,
    index_progress_needed=True,
    verification_progress_needed=True,
):
    """
    Read coordinator resumeData and globalState from the mongosync internal DB.

    Returns a dict with state, phase, lagTimeSeconds, start, finish, reversible,
    writeBlockingMode, buildIndexes, detectRandomId, copiedBytes, totalBytes,
    collectionsCopied, collectionsTotal, partitionsCopied, partitionsTotal,
    phaseTransitions (display-ready list of {phase, startedAt}),
    naturalOrderRows (list of {database, collections} or None),
    namespaceFilterActive, inclusionFilterRows, exclusionFilterRows,
    verificationModeRaw (globalState.verificationMode),
    indexCollectionsTotal, indexIndexesTotal, indexIndexesBuilt, indexCollectionsFinished
    (from indexCorrection counters plus throttled destination index-name verification when
    buildIndexes is not never and index_progress_needed is True).
    verificationProgress (from verifier persistence DBs when verification is enabled,
    verification_progress_needed is True, and phase gating allows it).
    """
    from .app_config import INDEX_BUILD_REFRESH_TIME, get_database, resolve_internal_db_name
    from .live_verifier_metadata import fetch_verifier_persistence_status

    internal_db_name = resolve_internal_db_name(connection_string)
    try:
        db = get_database(connection_string, internal_db_name)
        resume_data = db.resumeData.find_one({"_id": "coordinator"})
        global_state = db.globalState.find_one({})
    except PyMongoError as e:
        logger.error("Failed to read metadata status: %s", e)
        raise MetadataFetchError(
            "Could not read mongosync metadata from the internal database."
        ) from e

    state = resume_data.get("state") if resume_data else None
    sync_phase = resume_data.get("syncPhase") if resume_data else None
    phase = sync_phase.capitalize() if sync_phase else None

    phase_transitions = resume_data.get("phaseTransitions", []) if resume_data else []
    phase_transition_rows = format_phase_transition_rows(phase_transitions)
    start_dt = get_phase_timestamp(phase_transitions, "initializing collections and indexes")
    finish_dt = get_phase_timestamp(phase_transitions, "commit completed")

    reversible_raw = global_state.get("reversible") if global_state else None
    detect_random_id_raw = global_state.get("detectRandomId") if global_state else None

    direction_mapping = resume_data.get("directionMapping") if resume_data else None
    direction_source = None
    direction_destination = None
    if isinstance(direction_mapping, dict):
        direction_source = direction_mapping.get("source") or direction_mapping.get("Source")
        direction_destination = (
            direction_mapping.get("destination") or direction_mapping.get("Destination")
        )

    copied_bytes, total_bytes = fetch_partition_byte_totals(db)
    collection_totals = fetch_collection_copy_totals(db)
    partition_totals = fetch_partition_phase_totals(db)

    build_indexes_raw = global_state.get("buildIndexes") if global_state else None
    index_correction_status = None
    if (
        build_indexes_raw != "never"
        and index_progress_needed
        and index_build_progress_allowed(build_indexes_raw, sync_phase)
    ):
        index_correction_status = fetch_index_correction_status(
            db,
            connection_string,
            refresh_sec=INDEX_BUILD_REFRESH_TIME,
        )
    verification_mode_raw = read_verification_mode_from_global_state(global_state)
    verification_progress = None
    if (
        verification_progress_needed
        and verification_progress_allowed(verification_mode_raw, sync_phase)
    ):
        verification_progress = fetch_verifier_persistence_status(connection_string)
    natural_order_filter = (
        global_state.get("copyInNaturalOrderFilter") if global_state else None
    )
    natural_order_rows = parse_copy_in_natural_order_filter(natural_order_filter)
    namespace_filter = global_state.get("namespaceFilter") if global_state else None
    inclusion_filter = (
        namespace_filter.get("inclusionFilter") if namespace_filter else None
    )
    exclusion_filter = (
        namespace_filter.get("exclusionFilter") if namespace_filter else None
    )

    result = {
        "state": state,
        "phase": phase,
        "syncPhase": sync_phase,
        "lagTimeSeconds": compute_lag_time_seconds(resume_data),
        "start": _format_timestamp(start_dt),
        "finish": _format_timestamp(finish_dt),
        "reversible": str(reversible_raw) if reversible_raw is not None else None,
        "writeBlockingMode": format_write_blocking_mode(
            global_state.get("writeBlockingMode") if global_state else None
        ),
        "buildIndexesRaw": build_indexes_raw,
        "buildIndexes": format_build_indexes(build_indexes_raw),
        "verificationModeRaw": verification_mode_raw,
        "detectRandomId": (
            str(detect_random_id_raw) if detect_random_id_raw is not None else None
        ),
        "directionSource": direction_source,
        "directionDestination": direction_destination,
        "copiedBytes": copied_bytes,
        "totalBytes": total_bytes,
        "collectionsCopied": None,
        "collectionsTotal": None,
        "partitionsCopied": None,
        "partitionsTotal": None,
        "indexCollectionsTotal": None,
        "indexIndexesTotal": None,
        "indexIndexesBuilt": None,
        "indexCollectionsFinished": None,
        "phaseTransitions": phase_transition_rows,
        "naturalOrderRows": natural_order_rows,
        "namespaceFilterActive": namespace_filter_is_active(namespace_filter),
        "inclusionFilterRows": format_namespace_filter_rows(
            inclusion_filter, "inclusion"
        ),
        "exclusionFilterRows": format_namespace_filter_rows(
            exclusion_filter, "exclusion"
        ),
    }
    if collection_totals:
        result["collectionsCopied"] = collection_totals["collectionsCopied"]
        result["collectionsTotal"] = collection_totals["collectionsTotal"]
    if partition_totals:
        result["partitionsCopied"] = partition_totals["partitionsCopied"]
        result["partitionsTotal"] = partition_totals["partitionsTotal"]
    if index_correction_status:
        result["indexCollectionsTotal"] = index_correction_status["collectionsTotal"]
        result["indexIndexesTotal"] = index_correction_status["indexesTotal"]
        result["indexIndexesBuilt"] = index_correction_status["indexesBuilt"]
        result["indexCollectionsFinished"] = index_correction_status["collectionsFinished"]
    if verification_progress:
        result["verificationProgress"] = verification_progress
    return result
