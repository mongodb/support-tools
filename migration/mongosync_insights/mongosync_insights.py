import logging
import sys
import os
from flask import Flask, render_template, request, make_response, jsonify, send_from_directory
from lib.logs_metrics import upload_file
from lib.live_migration_metrics import plotMetrics, gatherMetrics, gatherPartitionsMetrics, gatherEndpointMetrics
from lib.migration_verifier import plotVerifierMetrics, gatherVerifierMetrics
from pymongo.errors import InvalidURI, PyMongoError
from lib.app_config import (
    setup_logging, validate_config, get_app_info, HOST, PORT, MAX_FILE_SIZE, 
    REFRESH_TIME, APP_VERSION, DEVELOPER_CREDITS, validate_connection, clear_connection_cache, 
    SECURE_COOKIES, CONNECTION_STRING, VERIFIER_CONNECTION_STRING,
    PROGRESS_ENDPOINT_URL, validate_progress_endpoint_url, session_store, SESSION_TIMEOUT,
    LOG_STORE_DIR, LOG_STORE_MAX_AGE_HOURS,
)
from lib.connection_validator import sanitize_for_display
from lib.log_store import LogStore
from lib.log_store_registry import log_store_registry
from lib.snapshot_store import (
    load_snapshot, list_snapshots as get_snapshot_list,
    delete_snapshot as remove_snapshot, cleanup_old_snapshots,
)

# Cookie name for session ID
SESSION_COOKIE_NAME = 'mi_session_id'

def _store_session_data(new_data):
    """Merge new_data into the existing session or create a fresh one."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id and session_store.update_session(session_id, new_data):
        return session_id
    return session_store.create_session(new_data)

# Validate configuration on startup
try:
    validate_config()
except (PermissionError, ValueError) as e:
    print(f"Configuration error: {e}")
    exit(1)

# Setup logging
logger = setup_logging()

# Resolve base path for templates & static assets (supports PyInstaller bundles)
if getattr(sys, 'frozen', False):
    _base_path = sys._MEIPASS
else:
    _base_path = os.path.dirname(os.path.abspath(__file__))

# Create a Flask app
app = Flask(__name__,
            template_folder=os.path.join(_base_path, 'templates'),
            static_folder=os.path.join(_base_path, 'images'),
            static_url_path='/images')

# Configure Flask for file uploads
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE


@app.route('/static/js/<path:filename>')
def mi_static_js(filename):
    """Serve shared JS (static_folder is reserved for /images)."""
    return send_from_directory(os.path.join(_base_path, 'static', 'js'), filename)


# Add security headers to all responses
@app.after_request
def add_security_headers(response):
    """Add security headers to all HTTP responses."""
    # Enforce HTTPS and prevent downgrade attacks
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Prevent MIME type sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    # Prevent clickjacking attacks
    response.headers['X-Frame-Options'] = 'DENY'
    
    # Control referrer information
    response.headers['Referrer-Policy'] = 'no-referrer'
    
    # Content Security Policy - configured to work with Plotly charts
    # Note: Plotly requires 'unsafe-inline' and 'unsafe-eval' for rendering
    # Note: blob: is required for Plotly snapshot/download functionality
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.plot.ly; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data:; "
        "connect-src 'self' blob:;"
    )
    
    # Additional security headers
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    
    return response

# Make app version available to all templates
@app.context_processor
def inject_app_version():
    return dict(app_version=APP_VERSION, developer_credits=DEVELOPER_CREDITS)

# Handle file too large error
@app.errorhandler(413)
def too_large(e):
    max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
    return render_template('error.html',
                         error_title="File Too Large",
                         error_message=f"File size exceeds maximum allowed size ({max_size_mb:.1f} MB)."), 413

@app.route('/')
def home_page(): 
    # Calculate max file size in GB for display
    max_file_size_gb = MAX_FILE_SIZE / (1024 * 1024 * 1024)
    
    if not CONNECTION_STRING:
        connection_string_form = '''<label for="connectionString">Atlas MongoDB Connection String:</label>  
                                    <input type="text" id="connectionString" name="connectionString" size="47" autocomplete="off"
                                        placeholder="mongodb+srv://usr:pwd@cluster0.mongodb.net/"><br><br>'''
    else:
        # Use safe sanitization for display
        sanitized_connection = sanitize_for_display(CONNECTION_STRING)
        connection_string_form = f"<p><b>Connecting to Destination Cluster at: </b>{sanitized_connection}</p>"

    if not PROGRESS_ENDPOINT_URL:
        progress_endpoint_form = '''<label for="progressEndpointUrl">Mongosync Progress Endpoint URL:</label>  
                                    <input type="text" id="progressEndpointUrl" name="progressEndpointUrl" size="47" autocomplete="off"
                                        placeholder="host:port/api/v1/progress"><br><br>'''
    else:
        progress_endpoint_form = f"<p><b>Mongosync Progress Endpoint: </b>{PROGRESS_ENDPOINT_URL}</p>"

    # Migration verifier connection string form
    if not VERIFIER_CONNECTION_STRING:
        verifier_connection_string_form = '''<label for="verifierConnectionString">Verifier MongoDB Connection String:</label>  
                                    <input type="text" id="verifierConnectionString" name="verifierConnectionString" size="47" autocomplete="off"
                                        placeholder="mongodb+srv://usr:pwd@cluster0.mongodb.net/"><br><br>'''
    else:
        sanitized_connection = sanitize_for_display(VERIFIER_CONNECTION_STRING)
        verifier_connection_string_form = f"<p><b>Connecting to Verifier DB at: </b>{sanitized_connection}</p>"

    return render_template('home.html', 
                           connection_string_form=connection_string_form,
                           progress_endpoint_form=progress_endpoint_form,
                           verifier_connection_string_form=verifier_connection_string_form,
                           max_file_size_gb=max_file_size_gb)


@app.route('/logout', methods=['POST'])
def logout():
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session_store.delete_session(session_id)
    log_store_registry.cleanup_expired()
    cleanup_old_snapshots(LOG_STORE_DIR, LOG_STORE_MAX_AGE_HOURS)
    response = make_response('', 200)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.route('/uploadLogs', methods=['POST'])
def uploadLogs():
    return upload_file()

@app.route('/search_logs')
def search_logs():
    """Full-text search across the uploaded log file via SQLite FTS5."""
    store_id = request.args.get('store_id', '').strip()
    if not store_id:
        return jsonify({'error': 'Missing store_id parameter'}), 400

    q = request.args.get('q', '').strip()
    level = request.args.get('level', '').strip()
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    try:
        per_page = min(max(1, int(request.args.get('per_page', 50))), 200)
    except (ValueError, TypeError):
        per_page = 50

    store = log_store_registry.open_store(store_id)
    if store is None:
        return jsonify({'error': 'Log store not found or expired'}), 404

    try:
        query = {}
        if level:
            query['level'] = level
        if q:
            query['$text'] = q

        result = store.find(query, skip=(page - 1) * per_page, limit=per_page)
        result['page'] = page
        result['per_page'] = per_page
        return jsonify(result)
    except Exception as e:
        logger.error(f"Log search error: {e}")
        return jsonify({'error': 'Search failed', 'detail': str(e)}), 500

@app.route('/list_snapshots')
def list_snapshots_route():
    """Return JSON list of saved analysis snapshots."""
    try:
        snapshots = get_snapshot_list()
        return jsonify(snapshots)
    except Exception as e:
        logger.error(f"Error listing snapshots: {e}")
        return jsonify([])

@app.route('/load_snapshot/<snapshot_id>')
def load_snapshot_route(snapshot_id):
    """Load a saved analysis snapshot and render the results page."""
    data = load_snapshot(snapshot_id)
    if data is None:
        return render_template('error.html',
                             error_title="Snapshot Not Found",
                             error_message="The requested analysis snapshot was not found or has expired. "
                                           "Please upload and parse the log file again.")

    store_id = data.get('log_store_id', '')
    if store_id:
        from lib.snapshot_store import logstore_path
        db_path = logstore_path(store_id)
        if os.path.exists(db_path):
            log_store_registry.register(store_id, db_path)

    template_data = data.get('template_data', {})
    return render_template('upload_results.html', **template_data)

@app.route('/delete_snapshot/<snapshot_id>', methods=['DELETE'])
def delete_snapshot_route(snapshot_id):
    """Delete a saved analysis snapshot."""
    deleted, store_id = remove_snapshot(snapshot_id)
    if store_id:
        log_store_registry.remove(store_id)
    if deleted:
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Snapshot not found'}), 404



@app.route('/liveMonitoring', methods=['POST'])
def liveMonitoring():
    # Get connection string from env var or form (no caching)
    if CONNECTION_STRING:
        TARGET_MONGO_URI = CONNECTION_STRING
    else:
        TARGET_MONGO_URI = request.form.get('connectionString')
        if TARGET_MONGO_URI:
            TARGET_MONGO_URI = TARGET_MONGO_URI.strip() if TARGET_MONGO_URI.strip() else None

    # Get progress endpoint URL from env var or form (no caching)
    if PROGRESS_ENDPOINT_URL:
        progress_url = PROGRESS_ENDPOINT_URL
    else:
        progress_url = request.form.get('progressEndpointUrl')
        if progress_url:
            progress_url = progress_url.strip() if progress_url.strip() else None

    # Validate that at least one field is provided
    if not TARGET_MONGO_URI and not progress_url:
        logger.error("No connection string or progress endpoint URL provided")
        return render_template('error.html',
                             error_title="No Input Provided",
                             error_message="Please provide at least one of the following: MongoDB Connection String or Mongosync Progress Endpoint URL (or both).")

    # Validate progress endpoint URL format if provided
    if progress_url:
        if not validate_progress_endpoint_url(progress_url):
            logger.error(f"Invalid progress endpoint URL format: {progress_url}")
            return render_template('error.html',
                                 error_title="Invalid Progress Endpoint URL",
                                 error_message="The Progress Endpoint URL format is invalid. Expected format: host:port/api/v1/progress (e.g., localhost:27182/api/v1/progress)")

    # Test MongoDB connection if connection string is provided
    if TARGET_MONGO_URI:
        try:
            # Connection test (network, authentication)
            validate_connection(TARGET_MONGO_URI)
                
        except InvalidURI as e:
            clear_connection_cache()
            logger.error(f"Invalid connection string format: {e}")
            return render_template('error.html',
                                error_title="Invalid Connection String",
                                error_message="The connection string format is invalid. Please check your MongoDB connection string and try again.")
        except PyMongoError as e:
            clear_connection_cache()
            logger.error(f"Failed to connect: {e}")
            return render_template('error.html',
                                error_title="Connection Failed",
                                error_message="Could not connect to MongoDB. Please verify your credentials, network connectivity, and that the cluster is accessible.")
        except Exception as e:
            clear_connection_cache()
            logger.error(f"Unexpected error during connection validation: {e}")
            return render_template('error.html',
                                error_title="Connection Error",
                                error_message="An unexpected error occurred. Please try again.")

    # Store credentials in server-side in-memory session store (merge into existing session)
    session_data = {
        'connection_string': TARGET_MONGO_URI,
        'endpoint_url': progress_url
    }
    session_id = _store_session_data(session_data)

    # Determine which tabs to show (pass only boolean flags to template, not credentials)
    has_connection_string = bool(TARGET_MONGO_URI)
    has_endpoint_url = bool(progress_url)
    
    # Render the metrics page
    response = make_response(plotMetrics(
        has_connection_string=has_connection_string, 
        has_endpoint_url=has_endpoint_url
    ))
    
    # Set session ID in a secure cookie
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        httponly=True,  # Prevent JavaScript access
        secure=SECURE_COOKIES,  # Only send over HTTPS when enabled
        samesite='Strict',  # CSRF protection
        max_age=SESSION_TIMEOUT
    )
    
    return response

@app.route('/getLiveMonitoring', methods=['POST'])
def getLiveMonitoring():
    # Get connection string from env var or in-memory session store
    if CONNECTION_STRING:
        connection_string = CONNECTION_STRING
    else:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = session_store.get_session(session_id)
        connection_string = session_data.get('connection_string')
    
    if not connection_string:
        logger.error("No connection string available for metrics refresh")
        return jsonify({"error": "No connection string available. Please refresh the page and re-enter your credentials."}), 400
    
    return jsonify(gatherMetrics(connection_string))

@app.route('/getPartitionsData', methods=['POST'])
def getPartitionsData():
    # Get connection string from env var or in-memory session store
    if CONNECTION_STRING:
        connection_string = CONNECTION_STRING
    else:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = session_store.get_session(session_id)
        connection_string = session_data.get('connection_string')
    
    if not connection_string:
        logger.error("No connection string available for partitions data refresh")
        return jsonify({"error": "No connection string available. Please refresh the page and re-enter your credentials."}), 400
    
    return jsonify(gatherPartitionsMetrics(connection_string))

@app.route('/getEndpointData', methods=['POST'])
def getEndpointData():
    # Get endpoint URL from env var or in-memory session store
    if PROGRESS_ENDPOINT_URL:
        endpoint_url = PROGRESS_ENDPOINT_URL
    else:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = session_store.get_session(session_id)
        endpoint_url = session_data.get('endpoint_url')
    
    if not endpoint_url:
        logger.error("No progress endpoint URL available for endpoint data refresh")
        return jsonify({"error": "No progress endpoint URL available. Please refresh the page and re-enter your credentials."}), 400
    
    return jsonify(gatherEndpointMetrics(endpoint_url))

@app.route('/Verifier', methods=['POST'])
def Verifier():
    """Render the migration verifier monitoring page."""
    # Get connection string from env var or form
    if VERIFIER_CONNECTION_STRING:
        TARGET_MONGO_URI = VERIFIER_CONNECTION_STRING
    else:
        TARGET_MONGO_URI = request.form.get('verifierConnectionString')
        if TARGET_MONGO_URI:
            TARGET_MONGO_URI = TARGET_MONGO_URI.strip() if TARGET_MONGO_URI.strip() else None

    # Get database name from form (default: migration_verification_metadata)
    db_name = request.form.get('verifierDbName', 'migration_verification_metadata')
    if db_name:
        db_name = db_name.strip() if db_name.strip() else 'migration_verification_metadata'

    if not TARGET_MONGO_URI:
        logger.error("No connection string provided for migration verifier")
        return render_template('error.html',
                             error_title="No Connection String",
                             error_message="Please provide a MongoDB Connection String for the migration verifier database.")

    # Test MongoDB connection
    try:
        validate_connection(TARGET_MONGO_URI)
    except InvalidURI as e:
        logger.error(f"Invalid connection string format: {e}")
        clear_connection_cache()
        return render_template('error.html',
                            error_title="Invalid Connection String",
                            error_message="The connection string format is invalid. Please check your MongoDB connection string and try again.")
    except PyMongoError as e:
        logger.error(f"Failed to connect: {e}")
        clear_connection_cache()
        return render_template('error.html',
                            error_title="Connection Failed",
                            error_message="Could not connect to MongoDB. Please verify your credentials, network connectivity, and that the cluster is accessible.")
    except Exception as e:
        logger.error(f"Unexpected error during connection validation: {e}")
        clear_connection_cache()
        return render_template('error.html',
                            error_title="Connection Error",
                            error_message="An unexpected error occurred. Please try again.")

    # Store credentials in server-side in-memory session store (merge into existing session)
    session_data = {
        'verifier_connection_string': TARGET_MONGO_URI,
        'verifier_db_name': db_name
    }
    session_id = _store_session_data(session_data)

    # Render the verifier metrics page
    response = make_response(plotVerifierMetrics(db_name=db_name))
    
    # Set session ID in a secure cookie
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_id,
        httponly=True,
        secure=SECURE_COOKIES,
        samesite='Strict',
        max_age=SESSION_TIMEOUT
    )
    
    return response

@app.route('/getVerifierData', methods=['POST'])
def getVerifierData():
    """Get migration verifier metrics data for AJAX refresh."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    session_data = session_store.get_session(session_id)

    if VERIFIER_CONNECTION_STRING:
        connection_string = VERIFIER_CONNECTION_STRING
    else:
        connection_string = session_data.get('verifier_connection_string')
    
    if not connection_string:
        logger.error("No connection string available for verifier metrics refresh")
        return jsonify({"error": "No connection string available. Please refresh the page and re-enter your credentials."}), 400
    
    db_name = session_data.get('verifier_db_name', 'migration_verification_metadata')
    
    return jsonify(gatherVerifierMetrics(connection_string, db_name))

if __name__ == '__main__':
    # Log startup information
    app_info = get_app_info()
    logger.info(f"Starting {app_info['name']} v{app_info['version']}")
    logger.info(f"Log file: {app_info['log_file']}")
    logger.info(f"Server: {app_info['host']}:{app_info['port']}")
    
    # Clean up expired log store DB files and snapshots from previous runs
    LogStore.cleanup_old_stores(LOG_STORE_DIR, LOG_STORE_MAX_AGE_HOURS)
    cleanup_old_snapshots(LOG_STORE_DIR, LOG_STORE_MAX_AGE_HOURS)
    
    # Import SSL config
    from lib.app_config import SSL_ENABLED, SSL_CERT_PATH, SSL_KEY_PATH
    
    # Run the Flask app with or without SSL
    if SSL_ENABLED:
        import ssl

        # Verify certificate files exist
        if not os.path.exists(SSL_CERT_PATH):
            logger.error(f"SSL certificate not found: {SSL_CERT_PATH}")
            logger.error("Please provide a valid SSL certificate or set MI_SSL_ENABLED=false")
            exit(1)
        if not os.path.exists(SSL_KEY_PATH):
            logger.error(f"SSL key not found: {SSL_KEY_PATH}")
            logger.error("Please provide a valid SSL private key or set MI_SSL_ENABLED=false")
            exit(1)
        
        # Create SSL context
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(SSL_CERT_PATH, SSL_KEY_PATH)
        
        logger.info("HTTPS enabled - Starting with SSL/TLS encryption")
        logger.info(f"SSL Certificate: {SSL_CERT_PATH}")
        app.run(host=HOST, port=PORT, ssl_context=context)
    else:
        logger.warning("HTTPS disabled - Starting with HTTP (insecure)")
        logger.warning("For production use, enable HTTPS by setting MI_SSL_ENABLED=true")
        app.run(host=HOST, port=PORT)
