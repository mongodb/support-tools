import logging
from flask import Flask, render_template, request
from mongosync_plot_logs import upload_file
from mongosync_plot_metadata import plotMetrics, gatherMetrics
from pymongo.errors import InvalidURI, PyMongoError
from pymongo.uri_parser import parse_uri 
from app_config import (
    setup_logging, validate_config, get_app_info, HOST, PORT, MAX_FILE_SIZE, 
    REFRESH_TIME, APP_VERSION, validate_connection, clear_connection_cache, 
    SECURE_COOKIES, CONNECTION_STRING, get_validation_config, get_mongo_client
)
from connection_validator import (
    validate_connection_string_content, check_rate_limit, record_failed_attempt,
    clear_rate_limit, validate_required_database, sanitize_for_display,
    ConnectionValidationError
)

# Validate configuration on startup
try:
    validate_config()
except (PermissionError, ValueError) as e:
    print(f"Configuration error: {e}")
    exit(1)

# Setup logging
logger = setup_logging()

# Runtime connection string storage (not persisted to disk)
_runtime_connection_string = None

# Create a Flask app
app = Flask(__name__, static_folder='images', static_url_path='/images')

# Configure Flask for file uploads
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Security configuration
app.config['SESSION_COOKIE_SECURE'] = SECURE_COOKIES  # Only send cookies over HTTPS (configurable via env)
app.config['SESSION_COOKIE_HTTPONLY'] = True  # Prevent JavaScript access to session cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'  # CSRF protection
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # Session timeout (1 hour)

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
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.plot.ly; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data:; "
        "connect-src 'self';"
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
    if not CONNECTION_STRING:
        connection_string_form = '''<label for="connectionString">Atlas MongoDB Connection String:</label>  
                                    <input type="text" id="connectionString" name="connectionString" size="47" autocomplete="off"
                                        placeholder="mongodb+srv://usr:pwd@cluster0.mongodb.net/myDB"><br><br>'''
    else:
        # Use safe sanitization for display
        sanitized_connection = sanitize_for_display(CONNECTION_STRING)
        connection_string_form = f"<p><b>Connecting to Destination Cluster at: </b>{sanitized_connection}</p>"

    return render_template('home.html', connection_string_form=connection_string_form)


@app.route('/upload', methods=['POST'])
def uploadLogs():
    return upload_file()

@app.route('/renderMetrics', methods=['POST'])
def renderMetrics():
    global _runtime_connection_string
    
    # Get client IP for rate limiting
    client_ip = request.remote_addr
    
    # Get validation configuration
    config = get_validation_config()
    
    # Use environment variable if set, otherwise get from form or runtime cache
    if CONNECTION_STRING:
        TARGET_MONGO_URI = CONNECTION_STRING
    elif _runtime_connection_string:
        TARGET_MONGO_URI = _runtime_connection_string
    else:
        TARGET_MONGO_URI = request.form.get('connectionString')
        
        # Add validation for empty connection string
        if not TARGET_MONGO_URI or not TARGET_MONGO_URI.strip():
            logger.error("No connection string provided")
            return render_template('error.html',
                                 error_title="No connection string provided",
                                 error_message="Please provide a valid MongoDB connection string.")

    # Comprehensive validation chain
    try:
        # 1. Rate limiting check (prevent brute force)
        check_rate_limit(client_ip, config['max_attempts'], config['lockout_minutes'])
        
        # 2. Content validation (injection prevention, XSS, etc.)
        TARGET_MONGO_URI = validate_connection_string_content(TARGET_MONGO_URI, config)
        
        # 3. Connection test (network, authentication)
        validate_connection(TARGET_MONGO_URI)
        
        # 4. Required database validation (if enabled)
        if config['validate_required_db']:
            client = get_mongo_client(TARGET_MONGO_URI)
            validate_required_database(client, config['internal_db_name'])
        
        # Clear rate limit on successful validation
        clear_rate_limit(client_ip)
        
        # Cache connection string for subsequent AJAX calls (only if not from env var)
        if not CONNECTION_STRING:
            _runtime_connection_string = TARGET_MONGO_URI
            
    except ConnectionValidationError as e:
        # Validation error (content, rate limit, etc.)
        record_failed_attempt(client_ip)
        clear_connection_cache()
        _runtime_connection_string = None
        
        logger.error(f"Connection validation failed: {e}")
        return render_template('error.html',
                            error_title="Validation Error",
                            error_message=str(e))
    except InvalidURI as e:
        # Invalid connection string format
        record_failed_attempt(client_ip)
        clear_connection_cache()
        _runtime_connection_string = None
        
        logger.error(f"Invalid connection string format: {e}")
        return render_template('error.html',
                            error_title="Invalid Connection String",
                            error_message="The connection string format is invalid. Please check your MongoDB connection string and try again.")
    except PyMongoError as e:
        # Failed to connect (authentication, network, etc.)
        record_failed_attempt(client_ip)
        clear_connection_cache()
        _runtime_connection_string = None
        
        logger.error(f"Failed to connect: {e}")
        return render_template('error.html',
                            error_title="Connection Failed",
                            error_message="Could not connect to MongoDB. Please verify your credentials, network connectivity, and that the cluster is accessible.")
    except Exception as e:
        # Unexpected error
        record_failed_attempt(client_ip)
        clear_connection_cache()
        _runtime_connection_string = None
        
        logger.error(f"Unexpected error during connection validation: {e}")
        return render_template('error.html',
                            error_title="Connection Error",
                            error_message="An unexpected error occurred. Please try again.")

    return plotMetrics()

@app.route('/get_metrics_data', methods=['POST'])
def getMetrics():
    # Use environment variable if set, otherwise use runtime cache
    connection_string = CONNECTION_STRING if CONNECTION_STRING else _runtime_connection_string
    
    if not connection_string:
        logger.error("No connection string available for metrics refresh")
        return {"error": "No connection string available"}, 400
    
    return gatherMetrics(connection_string)

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
