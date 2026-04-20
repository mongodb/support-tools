import logging

from flask import Blueprint, jsonify, make_response, render_template, request

from lib.connection_validator import sanitize_for_display
from lib.live_migration_metrics import (
    gatherEndpointMetrics,
    gatherMetrics,
    gatherPartitionsMetrics,
    plotMetrics,
)
from lib.migration_verifier import gatherVerifierMetrics, plotVerifierMetrics
from lib.session_support import SESSION_COOKIE_NAME, store_session_data
from lib.app_config import (
    CONNECTION_STRING,
    PROGRESS_ENDPOINT_URL,
    SECURE_COOKIES,
    SESSION_TIMEOUT,
    VERIFIER_CONNECTION_STRING,
    clear_connection_cache,
    session_store,
    validate_connection,
    validate_progress_endpoint_url,
)
from pymongo.errors import InvalidURI, PyMongoError

bp = Blueprint("live", __name__, url_prefix="/live")

logger = logging.getLogger(__name__)


@bp.route("/")
def live_home():
    if not CONNECTION_STRING:
        connection_string_form = """<label for="connectionString">Atlas MongoDB Connection String:</label>  
                                    <input type="text" id="connectionString" name="connectionString" size="47" autocomplete="off"
                                        placeholder="mongodb+srv://usr:pwd@cluster0.mongodb.net/"><br><br>"""
    else:
        sanitized_connection = sanitize_for_display(CONNECTION_STRING)
        connection_string_form = f"<p><b>Connecting to Destination Cluster at: </b>{sanitized_connection}</p>"

    if not PROGRESS_ENDPOINT_URL:
        progress_endpoint_form = """<label for="progressEndpointUrl">Mongosync Progress Endpoint URL:</label>  
                                    <input type="text" id="progressEndpointUrl" name="progressEndpointUrl" size="47" autocomplete="off"
                                        placeholder="host:port/api/v1/progress"><br><br>"""
    else:
        progress_endpoint_form = f"<p><b>Mongosync Progress Endpoint: </b>{PROGRESS_ENDPOINT_URL}</p>"

    if not VERIFIER_CONNECTION_STRING:
        verifier_connection_string_form = """<label for="verifierConnectionString">Verifier MongoDB Connection String:</label>  
                                    <input type="text" id="verifierConnectionString" name="verifierConnectionString" size="47" autocomplete="off"
                                        placeholder="mongodb+srv://usr:pwd@cluster0.mongodb.net/"><br><br>"""
    else:
        sanitized_connection = sanitize_for_display(VERIFIER_CONNECTION_STRING)
        verifier_connection_string_form = f"<p><b>Connecting to Verifier DB at: </b>{sanitized_connection}</p>"

    return render_template(
        "live/home.html",
        connection_string_form=connection_string_form,
        progress_endpoint_form=progress_endpoint_form,
        verifier_connection_string_form=verifier_connection_string_form,
    )


@bp.route("/liveMonitoring", methods=["POST"])
def live_monitoring():
    if CONNECTION_STRING:
        target_mongo_uri = CONNECTION_STRING
    else:
        target_mongo_uri = request.form.get("connectionString")
        if target_mongo_uri:
            target_mongo_uri = target_mongo_uri.strip() if target_mongo_uri.strip() else None

    if PROGRESS_ENDPOINT_URL:
        progress_url = PROGRESS_ENDPOINT_URL
    else:
        progress_url = request.form.get("progressEndpointUrl")
        if progress_url:
            progress_url = progress_url.strip() if progress_url.strip() else None

    if not target_mongo_uri and not progress_url:
        logger.error("No connection string or progress endpoint URL provided")
        return render_template(
            "error.html",
            error_title="No Input Provided",
            error_message="Please provide at least one of the following: MongoDB Connection String or Mongosync Progress Endpoint URL (or both).",
        )

    if progress_url and not validate_progress_endpoint_url(progress_url):
        logger.error("Invalid progress endpoint URL format: %s", progress_url)
        return render_template(
            "error.html",
            error_title="Invalid Progress Endpoint URL",
            error_message="The Progress Endpoint URL format is invalid. Expected format: host:port/api/v1/progress (e.g., localhost:27182/api/v1/progress)",
        )

    if target_mongo_uri:
        try:
            validate_connection(target_mongo_uri)
        except InvalidURI as e:
            clear_connection_cache()
            logger.error("Invalid connection string format: %s", e)
            return render_template(
                "error.html",
                error_title="Invalid Connection String",
                error_message="The connection string format is invalid. Please check your MongoDB connection string and try again.",
            )
        except PyMongoError as e:
            clear_connection_cache()
            logger.error("Failed to connect: %s", e)
            return render_template(
                "error.html",
                error_title="Connection Failed",
                error_message="Could not connect to MongoDB. Please verify your credentials, network connectivity, and that the cluster is accessible.",
            )
        except Exception as e:
            clear_connection_cache()
            logger.error("Unexpected error during connection validation: %s", e)
            return render_template(
                "error.html",
                error_title="Connection Error",
                error_message="An unexpected error occurred. Please try again.",
            )

    session_data = {
        "connection_string": target_mongo_uri,
        "endpoint_url": progress_url,
    }
    session_id = store_session_data(session_data)

    has_connection_string = bool(target_mongo_uri)
    has_endpoint_url = bool(progress_url)

    response = make_response(
        plotMetrics(
            has_connection_string=has_connection_string,
            has_endpoint_url=has_endpoint_url,
        )
    )

    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="Strict",
        max_age=SESSION_TIMEOUT,
    )
    return response


@bp.route("/getLiveMonitoring", methods=["POST"])
def get_live_monitoring():
    if CONNECTION_STRING:
        connection_string = CONNECTION_STRING
    else:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = session_store.get_session(session_id)
        connection_string = session_data.get("connection_string") if session_data else None

    if not connection_string:
        logger.error("No connection string available for metrics refresh")
        return jsonify(
            {
                "error": "No connection string available. Please refresh the page and re-enter your credentials."
            }
        ), 400

    return jsonify(gatherMetrics(connection_string))


@bp.route("/getPartitionsData", methods=["POST"])
def get_partitions_data():
    if CONNECTION_STRING:
        connection_string = CONNECTION_STRING
    else:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = session_store.get_session(session_id)
        connection_string = session_data.get("connection_string") if session_data else None

    if not connection_string:
        logger.error("No connection string available for partitions data refresh")
        return jsonify(
            {
                "error": "No connection string available. Please refresh the page and re-enter your credentials."
            }
        ), 400

    return jsonify(gatherPartitionsMetrics(connection_string))


@bp.route("/getEndpointData", methods=["POST"])
def get_endpoint_data():
    if PROGRESS_ENDPOINT_URL:
        endpoint_url = PROGRESS_ENDPOINT_URL
    else:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = session_store.get_session(session_id)
        endpoint_url = session_data.get("endpoint_url") if session_data else None

    if not endpoint_url:
        logger.error("No progress endpoint URL available for endpoint data refresh")
        return jsonify(
            {
                "error": "No progress endpoint URL available. Please refresh the page and re-enter your credentials."
            }
        ), 400

    return jsonify(gatherEndpointMetrics(endpoint_url))


@bp.route("/Verifier", methods=["POST"])
def verifier():
    if VERIFIER_CONNECTION_STRING:
        target_mongo_uri = VERIFIER_CONNECTION_STRING
    else:
        target_mongo_uri = request.form.get("verifierConnectionString")
        if target_mongo_uri:
            target_mongo_uri = target_mongo_uri.strip() if target_mongo_uri.strip() else None

    db_name = request.form.get("verifierDbName", "migration_verification_metadata")
    if db_name:
        db_name = db_name.strip() if db_name.strip() else "migration_verification_metadata"

    if not target_mongo_uri:
        logger.error("No connection string provided for migration verifier")
        return render_template(
            "error.html",
            error_title="No Connection String",
            error_message="Please provide a MongoDB Connection String for the migration verifier database.",
        )

    try:
        validate_connection(target_mongo_uri)
    except InvalidURI as e:
        logger.error("Invalid connection string format: %s", e)
        clear_connection_cache()
        return render_template(
            "error.html",
            error_title="Invalid Connection String",
            error_message="The connection string format is invalid. Please check your MongoDB connection string and try again.",
        )
    except PyMongoError as e:
        logger.error("Failed to connect: %s", e)
        clear_connection_cache()
        return render_template(
            "error.html",
            error_title="Connection Failed",
            error_message="Could not connect to MongoDB. Please verify your credentials, network connectivity, and that the cluster is accessible.",
        )
    except Exception as e:
        logger.error("Unexpected error during connection validation: %s", e)
        clear_connection_cache()
        return render_template(
            "error.html",
            error_title="Connection Error",
            error_message="An unexpected error occurred. Please try again.",
        )

    session_data = {
        "verifier_connection_string": target_mongo_uri,
        "verifier_db_name": db_name,
    }
    session_id = store_session_data(session_data)

    response = make_response(plotVerifierMetrics(db_name=db_name))

    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite="Strict",
        max_age=SESSION_TIMEOUT,
    )
    return response


@bp.route("/getVerifierData", methods=["POST"])
def get_verifier_data():
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    session_data = session_store.get_session(session_id)

    if VERIFIER_CONNECTION_STRING:
        connection_string = VERIFIER_CONNECTION_STRING
    else:
        connection_string = (session_data or {}).get("verifier_connection_string")

    if not connection_string:
        logger.error("No connection string available for verifier metrics refresh")
        return jsonify(
            {
                "error": "No connection string available. Please refresh the page and re-enter your credentials."
            }
        ), 400

    db_name = (session_data or {}).get("verifier_db_name", "migration_verification_metadata")
    return jsonify(gatherVerifierMetrics(connection_string, db_name))
