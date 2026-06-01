import logging
import os

from flask import Blueprint, jsonify, render_template, request

from lib.logs_metrics import upload_file
from lib.log_store_registry import log_store_registry
from lib.snapshot_store import (
    load_snapshot,
    list_snapshots as get_snapshot_list,
    delete_snapshot as remove_snapshot,
)

bp = Blueprint("logs", __name__, url_prefix="/logs")

logger = logging.getLogger(__name__)


@bp.route("/")
def logs_home():
    from lib.app_config import (
        MAX_FILE_SIZE,
    )

    max_file_size_gb = MAX_FILE_SIZE / (1024**3)
    return render_template("logs/home.html", max_file_size_gb=max_file_size_gb)


@bp.route("/uploadLogs", methods=["POST"])
def upload_logs():
    return upload_file()


@bp.route("/search_logs")
def search_logs():
    store_id = request.args.get("store_id", "").strip()
    if not store_id:
        return jsonify({"error": "Missing store_id parameter"}), 400

    q = request.args.get("q", "").strip()
    level = request.args.get("level", "").strip()
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = min(max(1, int(request.args.get("per_page", 50))), 200)
    except (ValueError, TypeError):
        per_page = 50

    store = log_store_registry.open_store(store_id)
    if store is None:
        return jsonify({"error": "Log store not found or expired"}), 404

    try:
        query = {}
        if level:
            query["level"] = level
        if q:
            query["$text"] = q

        result = store.find(query, skip=(page - 1) * per_page, limit=per_page)
        result["page"] = page
        result["per_page"] = per_page
        return jsonify(result)
    except Exception as e:
        logger.error("Log search error: %s", e)
        return jsonify({"error": "Search failed", "detail": str(e)}), 500


@bp.route("/list_snapshots")
def list_snapshots():
    try:
        snapshots = get_snapshot_list()
        return jsonify(snapshots)
    except Exception as e:
        logger.error("Error listing snapshots: %s", e)
        return jsonify([])


@bp.route("/load_snapshot/<snapshot_id>")
def load_snapshot_view(snapshot_id):
    data = load_snapshot(snapshot_id)
    if data is None:
        return render_template(
            "error.html",
            error_title="Snapshot Not Found",
            error_message=(
                "The requested analysis snapshot was not found or has expired. "
                "Please upload and parse the log file again."
            ),
        )

    store_id = data.get("log_store_id", "")
    if store_id:
        from lib.snapshot_store import logstore_path

        db_path = logstore_path(store_id)
        if os.path.exists(db_path):
            log_store_registry.register(store_id, db_path)

    template_data = data.get("template_data", {})
    return render_template("upload_results.html", **template_data)


@bp.route("/delete_snapshot/<snapshot_id>", methods=["DELETE"])
def delete_snapshot_view(snapshot_id):
    deleted, store_id = remove_snapshot(snapshot_id)
    if store_id:
        log_store_registry.remove(store_id)
    if deleted:
        return jsonify({"status": "ok"})
    return jsonify({"error": "Snapshot not found"}), 404
