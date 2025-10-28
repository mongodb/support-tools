import logging
from flask import Flask, render_template, request
from mongosync_plot_logs import upload_file
from mongosync_plot_metadata import plotMetrics, gatherMetrics
from pymongo.errors import InvalidURI, PyMongoError
from pymongo.uri_parser import parse_uri 
from app_config import load_config, setup_logging, validate_config, get_app_info, HOST, PORT, MAX_FILE_SIZE, REFRESH_TIME, APP_VERSION, validate_connection, clear_connection_cache, SECURE_COOKIES

# Validate configuration on startup
try:
    validate_config()
except (PermissionError, ValueError) as e:
    print(f"Configuration error: {e}")
    exit(1)

# Setup logging
logger = setup_logging()

# Load configuration
config = load_config()

# Create a Flask app
app = Flask(__name__)

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
def home_page(message=""):
    if message == "invalid connection string":
        connection_string_form = '''<label for="connectionString"><b>The connection string provided is invalid, please provide a valid connection string.</b></label>  
                                    <input type="text" id="connectionString" name="connectionString" size="47"   
                                        placeholder="mongodb+srv://usr:pwd@cluster0.mongodb.net/myDB"><br><br>'''
    elif not config['LiveMonitor']['connectionString']:
        connection_string_form = '''<label for="connectionString">Atlas MongoDB Connection String:</label>  
                                    <input type="text" id="connectionString" name="connectionString" size="47"   
                                        placeholder="mongodb+srv://usr:pwd@cluster0.mongodb.net/myDB"><br><br>'''
    else:
        parsed = parse_uri(config['LiveMonitor']['connectionString'])  
        hosts = parsed['nodelist']
        hosts_str = ", ".join([f"{host}:{port}" for host, port in hosts])  
        connection_string_form = f"<p><b>Connecting to Destination Cluster at: </b>{hosts_str}</p>"

    return render_template('home.html', connection_string_form=connection_string_form)


@app.route('/upload', methods=['POST'])
def uploadLogs():
    return upload_file()

@app.route('/renderMetrics', methods=['POST'])
def renderMetrics():

    refreshTime = str(REFRESH_TIME)

    # If the connectionString is empty in the config, get it from the form and save it
    if config['LiveMonitor']['connectionString']:
        TARGET_MONGO_URI = config['LiveMonitor']['connectionString']
    else:
        TARGET_MONGO_URI = request.form.get('connectionString')
        config['LiveMonitor']['connectionString'] = TARGET_MONGO_URI
        config['LiveMonitor']['refreshTime'] = refreshTime
        from app_config import save_config
        save_config(config) 

    # Validate the connection string 
    # If valid proceed to plot
    # If not, return to home 
    try:  
        validate_connection(TARGET_MONGO_URI)
        return plotMetrics()
    except (InvalidURI, PyMongoError) as e:  
        logging.error(f"{e}. Invalid MongoDB connection string: "+ TARGET_MONGO_URI)
        
        # Clear connection cache when connection string changes
        clear_connection_cache()
        
        config['LiveMonitor']['connectionString'] = ""
        config['LiveMonitor']['refreshTime'] = refreshTime
        from app_config import save_config
        save_config(config)   
        
        return home_page("invalid connection string")

    #return plotMetrics()

@app.route('/get_metrics_data', methods=['POST'])
def getMetrics():
    return gatherMetrics()

if __name__ == '__main__':
    # Log startup information
    app_info = get_app_info()
    logger.info(f"Starting {app_info['name']} v{app_info['version']}")
    logger.info(f"Configuration file: {app_info['config_path']}")
    logger.info(f"Log file: {app_info['log_file']}")
    logger.info(f"Server: {app_info['host']}:{app_info['port']}")
    
    # Run the Flask app
    app.run(host=HOST, port=PORT)
