"""Live progress monitor: fetch /api/v1/progress and build a JSON view for the HTML dashboard."""

import json
import logging

import requests

from .connection_validator import sanitize_for_display
from .live_metadata_status import (
    MetadataFetchError,
    describe_build_indexes_policy,
    describe_verification_mode,
    fetch_metadata_status,
    index_build_progress_allowed,
    normalize_verification_mode,
    should_suppress_index_build_progress,
    verification_progress_allowed,
)
from .utils import (
    format_bytes_compact,
    format_count,
    format_lag_time_seconds,
    format_ratio,
)

logger = logging.getLogger(__name__)

_PROGRESS_FETCH_TIMEOUT = 10


class ProgressFetchError(Exception):
    """Raised when the progress endpoint cannot be reached or returns invalid data."""

    def __init__(self, message, *, kind="request"):
        super().__init__(message)
        self.kind = kind


def fetch_progress(endpoint_url):
    """
    GET mongosync progress JSON from host:port/api/v1/progress.

    Returns:
        tuple[dict, list]: (progress dict, warnings list)

    Raises:
        ProgressFetchError: on timeout, connection, HTTP, or JSON errors.
    """
    url = f"http://{endpoint_url}"
    logger.info("Fetching progress from endpoint: %s", url)
    try:
        response = requests.get(url, timeout=_PROGRESS_FETCH_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout as e:
        raise ProgressFetchError(
            "Timeout — could not reach the progress endpoint.", kind="timeout"
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise ProgressFetchError(
            "Connection error — could not reach the progress endpoint.", kind="connection"
        ) from e
    except requests.exceptions.HTTPError as e:
        raise ProgressFetchError(
            f"HTTP error from progress endpoint ({e.response.status_code}).", kind="http"
        ) from e
    except requests.exceptions.RequestException as e:
        raise ProgressFetchError(
            f"Request failed: {e}", kind="request"
        ) from e
    except json.JSONDecodeError as e:
        raise ProgressFetchError(
            "Invalid JSON response from progress endpoint.", kind="json"
        ) from e

    progress = data.get("progress") or {}
    warnings = progress.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = []
    return progress, warnings


def _state_badge_color(state_upper):
    mapping = {
        "RUNNING": "green",
        "IDLE": "gray",
        "INITIALIZING": "blue",
        "PAUSED": "yellow",
        "COMMITTING": "blue",
        "COMMITTED": "blue",
        "ERROR": "red",
        "FAILED": "red",
    }
    return mapping.get(state_upper, "gray")


def _derive_state_badge(progress):
    state = (progress.get("state") or "").upper()
    label = state or "—"
    return {"label": label, "color": _state_badge_color(state)}


def _derive_state_badge_from_state(state):
    state_upper = (state or "").upper()
    label = state_upper or "—"
    return {"label": label, "color": _state_badge_color(state_upper)}


def _api_base_url(endpoint_url):
    """Build http URL for UI subtitle (host:port/api/v1/progress)."""
    if not endpoint_url:
        return None
    return f"http://{endpoint_url}"


def _endpoint_meta(endpoint_url):
    """Shared endpoint fields for progress-monitor API responses."""
    return {
        "endpointDisplay": endpoint_url,
        "apiBaseUrl": _api_base_url(endpoint_url),
    }


def _build_connectivity(endpoint_url=None, connection_string=None):
    """Rows for the Connectivity card (endpoint URL and metadata connection string)."""
    rows = []
    if endpoint_url:
        rows.append(
            {
                "label": "Progress endpoint URL",
                "value": _api_base_url(endpoint_url),
            }
        )
    if connection_string:
        rows.append(
            {
                "label": "Metadata connection string",
                "value": sanitize_for_display(connection_string),
            }
        )
    if not rows:
        return None
    return {"title": "Connectivity", "rows": rows}


def _display_or_dash(value):
    if value is None or value == "":
        return "—"
    return str(value)


def _build_metadata_metrics(metadata):
    """Second metrics row from internal database (connection string required)."""
    if not metadata:
        return []
    return [
        {"label": "Start", "value": _display_or_dash(metadata.get("start")), "small": True},
        {"label": "Finish", "value": _display_or_dash(metadata.get("finish")), "small": True},
        {
            "label": "Reversible",
            "value": _display_or_dash(metadata.get("reversible")),
            "small": True,
        },
        {
            "label": "Write Blocking Mode",
            "value": _display_or_dash(metadata.get("writeBlockingMode")),
            "small": True,
        },
        {
            "label": "Build Indexes",
            "value": _display_or_dash(metadata.get("buildIndexes")),
            "small": True,
        },
        {
            "label": "Detect Random _id",
            "value": _display_or_dash(metadata.get("detectRandomId")),
            "small": True,
        },
    ]


def _build_progress_metrics(progress, lag_seconds):
    return [
        {"label": "Lag time", "value": format_lag_time_seconds(lag_seconds), "small": False},
        {"label": "Events applied", "value": format_count(progress.get("totalEventsApplied")), "small": False},
        {
            "label": "Oplog window left",
            "value": progress.get("estimatedOplogTimeRemaining") or "—",
            "small": True,
        },
        {
            "label": "Catch-up estimate",
            "value": format_lag_time_seconds(progress.get("estimatedSecondsToCEACatchup")),
            "small": True,
        },
        {
            "label": "Can commit",
            "value": "TRUE" if progress.get("canCommit") else "FALSE",
            "badge": "green" if progress.get("canCommit") else "gray",
            "small": True,
        },
        {
            "label": "Can write",
            "value": "TRUE" if progress.get("canWrite") else "FALSE",
            "badge": "green" if progress.get("canWrite") else "gray",
            "small": True,
        },
    ]


def _build_db_only_metrics(lag_seconds):
    return [
        {"label": "Lag time", "value": format_lag_time_seconds(lag_seconds), "small": False},
        {"label": "Events applied", "value": "—", "small": False},
        {"label": "Oplog window left", "value": "—", "small": True},
        {"label": "Catch-up estimate", "value": "—", "small": True},
        {"label": "Can commit", "value": "—", "small": True},
        {"label": "Can write", "value": "—", "small": True},
    ]


def _byte_copy_prefix(phase_lower):
    if "collection copy" in phase_lower:
        return "Data copied: "
    return "Copied: "


def _build_collections_copied_label(metadata):
    if not metadata:
        return None
    copied = metadata.get("collectionsCopied")
    total = metadata.get("collectionsTotal")
    if not total or total <= 0:
        return None
    if copied is None:
        copied = 0
    return f"Collections copied: {format_count(copied)} of {format_count(total)}"


def _build_partitions_copied_label(metadata):
    if not metadata:
        return None
    copied = metadata.get("partitionsCopied")
    total = metadata.get("partitionsTotal")
    if not total or total <= 0:
        return None
    if copied is None:
        copied = 0
    return f"Partitions copied: {format_count(copied)} of {format_count(total)}"


def _build_phase_start_times(metadata):
    if not metadata:
        return None
    rows = metadata.get("phaseTransitions") or []
    if not rows:
        return None
    return {
        "label": "Phase start times",
        "rows": rows,
        "timezoneNote": "UTC",
    }


def _build_sync_card(progress=None, metadata=None, *, progress_available=False):
    if progress_available and progress:
        info = progress.get("info") or ""
        info_lower = info.lower()
        phase = info or "—"
        lag_seconds = progress.get("lagTimeSeconds")
        metrics = _build_progress_metrics(progress, lag_seconds)

        collection_copy = progress.get("collectionCopy") or {}
        copied = collection_copy.get("estimatedCopiedBytes")
        total = collection_copy.get("estimatedTotalBytes")
        state = (progress.get("state") or "").upper()

        copy_percent = None
        if total and total > 0 and copied is not None:
            copy_percent = min(100.0, (copied / total) * 100)

        copy_indeterminate = copy_percent is None and state in ("RUNNING", "INITIALIZING")
        copy_prefix = _byte_copy_prefix(info_lower)
        copied_label = (
            f"{copy_prefix}{format_bytes_compact(copied)} of {format_bytes_compact(total)}"
        )

        return {
            "phase": phase,
            "copyPercent": copy_percent,
            "copyIndeterminate": copy_indeterminate,
            "copiedLabel": copied_label,
            "collectionsCopiedLabel": _build_collections_copied_label(metadata),
            "partitionsCopiedLabel": _build_partitions_copied_label(metadata),
            "showCopyProgress": True,
            "metrics": metrics,
            "metadataMetrics": _build_metadata_metrics(metadata),
            "phaseStartTimes": _build_phase_start_times(metadata),
        }

    phase = _display_or_dash(metadata.get("phase") if metadata else None)
    phase_lower = (metadata.get("phase") or "").lower() if metadata else ""
    lag_seconds = metadata.get("lagTimeSeconds") if metadata else None
    state = (metadata.get("state") or "").upper() if metadata else ""

    copied = metadata.get("copiedBytes") if metadata else None
    total = metadata.get("totalBytes") if metadata else None

    copy_percent = None
    copy_indeterminate = False
    copied_label = None
    show_copy_progress = False

    if total and total > 0 and copied is not None:
        copy_percent = min(100.0, (copied / total) * 100)
        copy_prefix = _byte_copy_prefix(phase_lower)
        copied_label = (
            f"{copy_prefix}{format_bytes_compact(copied)} of {format_bytes_compact(total)}"
        )
        show_copy_progress = True
    elif state in ("RUNNING", "INITIALIZING"):
        copy_indeterminate = True

    return {
        "phase": phase,
        "copyPercent": copy_percent,
        "copyIndeterminate": copy_indeterminate and not show_copy_progress,
        "copiedLabel": copied_label,
        "collectionsCopiedLabel": _build_collections_copied_label(metadata),
        "partitionsCopiedLabel": _build_partitions_copied_label(metadata),
        "showCopyProgress": show_copy_progress,
        "metrics": _build_db_only_metrics(lag_seconds),
        "metadataMetrics": _build_metadata_metrics(metadata),
        "phaseStartTimes": _build_phase_start_times(metadata),
    }


_INDEX_BUILDING_DESCRIPTION = (
    "Indexes rebuilt on the destination cluster after the data copy."
)

_INDEX_BUILDING_FALLBACK_DESCRIPTION_SUFFIX = (
    " Progress from metadata (approximate)."
)


def _build_index_building_card(
    built, total, coll_finished, coll_total, *, metadata_fallback=False
):
    if not total or not coll_total:
        return None

    percent = None
    if total > 0:
        percent = min(100.0, (built / total) * 100)

    description = _INDEX_BUILDING_DESCRIPTION
    if metadata_fallback:
        description += _INDEX_BUILDING_FALLBACK_DESCRIPTION_SUFFIX

    return {
        "title": "Index building",
        "description": description,
        "built": built,
        "total": total,
        "percent": percent,
        "summary": f"{format_count(built)} of {format_count(total)} indexes built",
        "metrics": [
            {
                "label": "Indexes built",
                "value": f"{format_count(built)} / {format_count(total)}",
                "small": True,
            },
            {
                "label": "Collections finished",
                "value": f"{format_count(coll_finished)} / {format_count(coll_total)}",
                "small": True,
            },
        ],
    }


def _build_index_building(progress):
    index_building = progress.get("indexBuilding")
    if not index_building or not isinstance(index_building, dict):
        return None

    return _build_index_building_card(
        built=index_building.get("indexesBuilt") or 0,
        total=index_building.get("totalIndexesToBuild") or 0,
        coll_finished=index_building.get("collectionsFinished") or 0,
        coll_total=index_building.get("collectionsTotal") or 0,
    )


def _build_index_building_from_metadata(metadata):
    if not metadata:
        return None
    if metadata.get("buildIndexesRaw") == "never":
        return None
    if not index_build_progress_allowed(
        metadata.get("buildIndexesRaw"),
        metadata.get("syncPhase"),
    ):
        return None
    return _build_index_building_card(
        built=metadata.get("indexIndexesBuilt") or 0,
        total=metadata.get("indexIndexesTotal") or 0,
        coll_finished=metadata.get("indexCollectionsFinished") or 0,
        coll_total=metadata.get("indexCollectionsTotal") or 0,
        metadata_fallback=True,
    )


def _build_index_building_info(metadata):
    if not metadata:
        return None
    message = describe_build_indexes_policy(metadata.get("buildIndexesRaw"))
    if not message:
        return None
    return {
        "title": "Index building",
        "description": message,
        "mode": "info",
    }


def _build_natural_order(metadata):
    if not metadata:
        return None
    rows = metadata.get("naturalOrderRows")
    if not rows:
        return None
    return {
        "title": "Copy in natural order",
        "description": (
            "These collections are copied in natural insertion order instead of parallel "
            "partitions. Mongosync uses this when _ids cannot be range-partitioned "
            "efficiently (for example random UUIDs or string keys), or when the "
            "collection is capped."
        ),
        "label": "Natural order collections",
        "rows": rows,
    }


def _build_filtered_migration(metadata):
    if not metadata or not metadata.get("namespaceFilterActive"):
        return None
    return {
        "title": "Filtered migration",
        "inclusion": {
            "label": "Include",
            "rows": metadata.get("inclusionFilterRows") or [],
        },
        "exclusion": {
            "label": "Exclude",
            "rows": metadata.get("exclusionFilterRows") or [],
        },
    }


def _build_direction_from_metadata(metadata):
    if not metadata:
        return None
    source_addr = metadata.get("directionSource")
    dest_addr = metadata.get("directionDestination")
    if not source_addr and not dest_addr:
        return None
    return {
        "source": {"address": source_addr or "—"},
        "destination": {"address": dest_addr or "—"},
    }


def _build_direction(progress):
    direction = progress.get("directionMapping") or {}
    source_addr = direction.get("Source")
    dest_addr = direction.get("Destination")
    if not source_addr and not dest_addr:
        return None

    source = progress.get("source") or {}
    destination = progress.get("destination") or {}

    def ping_label(side):
        ms = side.get("pingLatencyMs") if isinstance(side, dict) else None
        if ms is None or ms < 0:
            return "unreachable"
        return f"{ms} ms"

    return {
        "source": {"address": source_addr or "—", "ping": ping_label(source)},
        "destination": {"address": dest_addr or "—", "ping": ping_label(destination)},
    }


def _verification_side_kv(side_data):
    if not side_data:
        side_data = {}
    return [
        {"label": "Phase", "value": side_data.get("phase") or "—"},
        {
            "label": "Collections scanned",
            "value": format_ratio(
                side_data.get("scannedCollectionCount"),
                side_data.get("totalCollectionCount"),
            ),
        },
        {
            "label": "Documents hashed",
            "value": format_ratio(
                side_data.get("hashedDocumentCount"),
                side_data.get("estimatedDocumentCount"),
            ),
        },
        {
            "label": "Lag time",
            "value": format_lag_time_seconds(side_data.get("lagTimeSeconds")),
        },
    ]


_VERIFICATION_FALLBACK_DESCRIPTION_SUFFIX = (
    " Progress from verifier persistence metadata (approximate)."
)


def _build_verification(progress, *, metadata_fallback=False):
    verification = progress.get("verification")
    if not verification or not isinstance(verification, dict):
        return None

    description = "Progress of mongosync's embedded data verifier."
    if metadata_fallback:
        description += _VERIFICATION_FALLBACK_DESCRIPTION_SUFFIX

    return {
        "title": "Embedded Verifier",
        "description": description,
        "source": _verification_side_kv(verification.get("source")),
        "destination": _verification_side_kv(verification.get("destination")),
    }


def _progress_has_verification_data(progress):
    verification = (progress or {}).get("verification")
    if not verification or not isinstance(verification, dict):
        return False
    return bool(verification.get("source") or verification.get("destination"))


def _build_verification_info(metadata):
    message = describe_verification_mode(metadata.get("verificationModeRaw"))
    if not message:
        return None
    return {
        "title": "Embedded Verifier",
        "description": message,
        "mode": "info",
    }


def _resolve_verification_display(progress, metadata, *, progress_available=False):
    mode = normalize_verification_mode(
        metadata.get("verificationModeRaw") if metadata else None
    )
    if mode == "disabled":
        return _build_verification_info(metadata)
    if progress_available and progress and _progress_has_verification_data(progress):
        return _build_verification(progress)
    if metadata and metadata.get("verificationProgress"):
        if verification_progress_allowed(
            metadata.get("verificationModeRaw"),
            metadata.get("syncPhase"),
        ):
            card = _build_verification(
                {"verification": metadata["verificationProgress"]},
                metadata_fallback=True,
            )
            if card:
                return card
    if mode == "startAtCEA":
        return _build_verification_info(metadata)
    if progress_available and progress:
        return _build_verification(progress)
    return None


def _effective_progress_for_badges(progress, metadata, *, progress_available=False):
    """Merge metadata verifier fallback into progress for toolbar badge logic."""
    effective = dict(progress) if progress else {}
    if metadata and metadata.get("verificationProgress"):
        if not _progress_has_verification_data(effective):
            if verification_progress_allowed(
                metadata.get("verificationModeRaw"),
                metadata.get("syncPhase"),
            ):
                effective["verification"] = metadata["verificationProgress"]
    return effective if effective else None


_VERIFICATION_COMPLETE_PHASES = frozenset({"complete", "completed", "done", "finished"})
_VERIFICATION_INACTIVE_PHASES = frozenset({"not started", ""})


def _verification_side_complete(side_data):
    """
    Return True if side verification is complete, False if incomplete,
    or None if the side is not active (ignore for toolbar badge).
    """
    if not side_data or not isinstance(side_data, dict):
        return None

    hashed = side_data.get("hashedDocumentCount") or 0
    estimated = side_data.get("estimatedDocumentCount")
    if estimated and estimated > 0:
        return hashed >= estimated

    phase = (side_data.get("phase") or "").lower().strip()
    if phase in _VERIFICATION_COMPLETE_PHASES:
        return True
    if phase in _VERIFICATION_INACTIVE_PHASES:
        return None
    if phase:
        return False
    return None


def _verification_activity_active(progress, verification_card):
    if not verification_card or verification_card.get("mode") == "info":
        return False
    if not progress:
        return False

    verification = progress.get("verification") or {}
    active_statuses = []
    for side in ("source", "destination"):
        side_data = verification.get(side)
        if not side_data:
            continue
        status = _verification_side_complete(side_data)
        if status is not None:
            active_statuses.append(status)

    if not active_statuses:
        return False
    return not all(active_statuses)


def _index_build_activity_active(index_card):
    if not index_card or index_card.get("mode") == "info":
        return False
    total = index_card.get("total") or 0
    built = index_card.get("built") or 0
    return total > 0 and built < total


def _build_toolbar_badges(progress, verification_card, index_card):
    badges = []
    if _verification_activity_active(progress, verification_card):
        badges.append({"label": "VERIFYING", "color": "blue"})
    if _index_build_activity_active(index_card):
        badges.append({"label": "INDEXING", "color": "blue"})
    return badges


def _build_display(progress, metadata, *, progress_available=False):
    if progress_available and progress:
        state = (progress.get("state") or "").upper() or "—"
        state_badge = _derive_state_badge(progress)
    else:
        state = (metadata.get("state") or "").upper() if metadata else "—"
        state_badge = _derive_state_badge_from_state(metadata.get("state") if metadata else None)

    sync = _build_sync_card(
        progress=progress,
        metadata=metadata,
        progress_available=progress_available,
    )

    display = {
        "state": state or "—",
        "stateBadge": state_badge,
        "toolbarBadges": [],
        "sync": sync,
        "indexBuilding": None,
        "direction": None,
        "verification": None,
        "naturalOrder": None,
        "filteredMigration": None,
    }

    index_building = None
    if progress_available and progress:
        index_building = _build_index_building(progress)
        if index_building and metadata and should_suppress_index_build_progress(
            metadata.get("buildIndexesRaw"),
            metadata.get("syncPhase"),
        ):
            index_building = None
        display["direction"] = _build_direction(progress)
    if not index_building and metadata:
        index_building = _build_index_building_from_metadata(metadata)
    if not index_building and metadata:
        index_building = _build_index_building_info(metadata)
    display["indexBuilding"] = index_building

    display["verification"] = _resolve_verification_display(
        progress, metadata, progress_available=progress_available
    )
    effective_progress = _effective_progress_for_badges(
        progress if progress_available else None,
        metadata,
        progress_available=progress_available,
    )
    display["toolbarBadges"] = _build_toolbar_badges(
        effective_progress,
        display["verification"],
        display["indexBuilding"],
    )

    if not display["direction"] and metadata:
        display["direction"] = _build_direction_from_metadata(metadata)

    display["naturalOrder"] = _build_natural_order(metadata)
    display["filteredMigration"] = _build_filtered_migration(metadata)

    return display


def _progress_has_index_building(progress):
    if not progress:
        return False
    index_building = progress.get("indexBuilding")
    return isinstance(index_building, dict) and bool(index_building)


def build_live_monitor_payload(endpoint_url=None, connection_string=None):
    """
    Build the Live Monitoring tab payload from progress endpoint and/or metadata DB.
    """
    base = {
        **_endpoint_meta(endpoint_url),
        "warnings": [],
        "connectivity": _build_connectivity(endpoint_url, connection_string),
        "progressWarning": None,
        "metadataWarning": None,
        "display": None,
        "error": None,
    }

    progress = None
    warnings = []
    progress_available = False
    progress_warning = None
    metadata = None
    metadata_warning = None

    if endpoint_url:
        try:
            progress, warnings = fetch_progress(endpoint_url)
            progress_available = True
        except ProgressFetchError as e:
            progress_warning = f"Progress endpoint is not responding: {e}"
            logger.warning("Progress fetch failed: %s", e)

    if connection_string:
        index_progress_needed = not (
            progress_available and _progress_has_index_building(progress)
        )
        verification_progress_needed = not (
            progress_available and _progress_has_verification_data(progress)
        )
        try:
            metadata = fetch_metadata_status(
                connection_string,
                index_progress_needed=index_progress_needed,
                verification_progress_needed=verification_progress_needed,
            )
        except MetadataFetchError as e:
            metadata_warning = str(e)
            logger.warning("Metadata fetch failed: %s", e)

    if not progress_available and not metadata:
        errors = []
        if progress_warning:
            errors.append(progress_warning)
        if metadata_warning:
            errors.append(metadata_warning)
        if not errors:
            errors.append(
                "No progress endpoint URL or metadata connection string is configured."
            )
        base["error"] = " ".join(errors)
        base["progressWarning"] = progress_warning
        base["metadataWarning"] = metadata_warning
        return base

    base["warnings"] = warnings if progress_available else []
    base["progressWarning"] = progress_warning
    base["metadataWarning"] = metadata_warning
    base["display"] = _build_display(
        progress, metadata, progress_available=progress_available
    )
    return base


def progress_monitor_no_config_response(connection_string=None):
    """Response when neither progress endpoint nor metadata connection is configured."""
    return {
        **_endpoint_meta(None),
        "warnings": [],
        "connectivity": _build_connectivity(None, connection_string),
        "progressWarning": None,
        "metadataWarning": None,
        "display": None,
        "error": (
            "No progress endpoint or metadata connection string is configured. "
            "Return to Migration monitoring home and provide a Mongosync progress endpoint "
            "(host and port; path /api/v1/progress is fixed) and/or a metadata connection string, "
            "or set MI_PROGRESS_ENDPOINT_URL / MI_CONNECTION_STRING."
        ),
    }
