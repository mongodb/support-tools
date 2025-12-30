import logging
from flask import Flask, render_template, request, make_response
from mongosync_plot_logs import upload_file
from mongosync_plot_metadata import plotMetrics, gatherMetrics, gatherPartitionsMetrics, gatherEndpointMetrics
from pymongo.errors import InvalidURI, PyMongoError
from pymongo.uri_parser import parse_uri 
from app_config import (
    setup_logging, validate_config, get_app_info, HOST, PORT, MAX_FILE_SIZE, 
    REFRESH_TIME, APP_VERSION, validate_connection, clear_connection_cache, 
    SECURE_COOKIES, CONNECTION_STRING, get_mongo_client,
    PROGRESS_ENDPOINT_URL, validate_progress_endpoint_url, session_store, SESSION_TIMEOUT
)
from connection_validator import sanitize_for_display

# Cookie name for session ID
SESSION_COOKIE_NAME = 'mi_session_id'

# Validate configuration on startup
try:
    validate_config()
except (PermissionError, ValueError) as e:
    print(f"Configuration error: {e}")
    exit(1)

# Setup logging
logger = setup_logging()

# Create a Flask app
app = Flask(__name__, static_folder='images', static_url_path='/images')

# Configure Flask for file uploads
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

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
    return dict(app_version=APP_VERSION)

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

    return render_template('home.html', 
                           connection_string_form=connection_string_form,
                           progress_endpoint_form=progress_endpoint_form,
                           max_file_size_gb=max_file_size_gb)


@app.route('/upload', methods=['POST'])
def uploadLogs():
    return upload_file()

@app.route('/renderMetrics', methods=['POST'])
def renderMetrics():
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

    # Store credentials in server-side in-memory session store
    session_data = {
        'connection_string': TARGET_MONGO_URI,
        'endpoint_url': progress_url
    }
    session_id = session_store.create_session(session_data)

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

@app.route('/get_metrics_data', methods=['POST'])
def getMetrics():
    # Get connection string from env var or in-memory session store
    if CONNECTION_STRING:
        connection_string = CONNECTION_STRING
    else:
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = session_store.get_session(session_id)
        connection_string = session_data.get('connection_string')
    
    if not connection_string:
        logger.error("No connection string available for metrics refresh")
        return {"error": "No connection string available. Please refresh the page and re-enter your credentials."}, 400
    
    return gatherMetrics(connection_string)

@app.route('/get_partitions_data', methods=['POST'])
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
        return {"error": "No connection string available. Please refresh the page and re-enter your credentials."}, 400
    
    return gatherPartitionsMetrics(connection_string)

@app.route('/get_endpoint_data', methods=['POST'])
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
        return {"error": "No progress endpoint URL available. Please refresh the page and re-enter your credentials."}, 400
    
    return gatherEndpointMetrics(endpoint_url)

if __name__ == '__main__':
    # Log startup information
    app_info = get_app_info()
    logger.info(f"Starting {app_info['name']} v{app_info['version']}")
    logger.info(f"Log file: {app_info['log_file']}")
    logger.info(f"Server: {app_info['host']}:{app_info['port']}")
    
    # Import SSL config
    from app_config import SSL_ENABLED, SSL_CERT_PATH, SSL_KEY_PATH
    
    # Run the Flask app with or without SSL
    if SSL_ENABLED:
        import ssl
        import os
        
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
