"""
Configuration management for Mongosync Insights.
Supports environment variables and configurable paths.
"""
import os
import re
import logging
import uuid
import time
import threading
from pathlib import Path
from functools import lru_cache
import certifi
from pymongo import MongoClient
from pymongo.errors import PyMongoError, InvalidURI

# Environment variable configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('MI_LOG_FILE', 'insights.log')
HOST = os.getenv('MI_HOST', '127.0.0.1')
PORT = int(os.getenv('MI_PORT', '3030'))

# Application constants
APP_NAME = "Mongosync Insights"
APP_VERSION = "0.8.0.18"

# File upload settings
MAX_FILE_SIZE = int(os.getenv('MI_MAX_FILE_SIZE', str(10 * 1024 * 1024 * 1024)))  # 10GB default
ALLOWED_EXTENSIONS = {'.log', '.json', '.out', '.gz', '.zip', '.bz2', '.tar.gz', '.tgz', '.tar.bz2'}
ALLOWED_MIME_TYPES = [
    'application/x-ndjson',
    'application/gzip', 'application/x-gzip',
    'application/zip', 'application/x-zip-compressed',
    'application/x-bzip2',
    'application/x-tar',  # Tar archives
    'application/octet-stream'  # Generic binary (often used for compressed files)
]

# Compressed file MIME types (subset of ALLOWED_MIME_TYPES)
COMPRESSED_MIME_TYPES = {
    'application/gzip', 'application/x-gzip',
    'application/zip', 'application/x-zip-compressed',
    'application/x-bzip2',
    'application/x-tar',  # Tar archives
    'application/octet-stream'  # Generic binary (often used for compressed files)
}

# File extension to compression type mapping (for octet-stream fallback and tar detection)
EXTENSION_TO_COMPRESSION = {
    '.gz': 'gzip',
    '.zip': 'zip',
    '.bz2': 'bzip2',
    '.tar.gz': 'tar_gzip',
    '.tgz': 'tar_gzip',
    '.tar.bz2': 'tar_bzip2'
}

# File type patterns for identification
# mongosync logs: mongosync.log or mongosync-* (but NOT mongosync_metrics*) or liveimport_*
MONGOSYNC_LOG_PATTERN = re.compile(r'^mongosync\.log$|^mongosync-(?!metrics).*|^liveimport_.*', re.IGNORECASE)
# mongosync metrics: mongosync_metrics.log or mongosync_metrics-*
MONGOSYNC_METRICS_PATTERN = re.compile(r'^mongosync_metrics\.log$|^mongosync_metrics-.*', re.IGNORECASE)


def classify_file_type(filename: str) -> str:
    """
    Classify a file as mongosync logs, mongosync metrics, or unknown based on filename pattern.
    
    Args:
        filename: The filename to classify (can include path, only basename is used)
        
    Returns:
        'logs' for mongosync log files
        'metrics' for mongosync metrics files
        None for unrecognized files
    """
    import os
    # Extract just the filename without path
    basename = os.path.basename(filename)
    
    # Remove compression extensions to get the base name
    # Handle compound extensions like .log.gz, .log.1.gz, etc.
    name_without_compression = basename
    for ext in ['.gz', '.bz2', '.zip']:
        if name_without_compression.lower().endswith(ext):
            name_without_compression = name_without_compression[:-len(ext)]
    
    # Check patterns against the name without compression extension
    if MONGOSYNC_METRICS_PATTERN.match(name_without_compression):
        return 'metrics'
    elif MONGOSYNC_LOG_PATTERN.match(name_without_compression):
        return 'logs'
    
    # Also check the original basename in case pattern includes extension
    if MONGOSYNC_METRICS_PATTERN.match(basename):
        return 'metrics'
    elif MONGOSYNC_LOG_PATTERN.match(basename):
        return 'logs'
    
    return None


# Security settings
SECURE_COOKIES = os.getenv('MI_SECURE_COOKIES', 'True').lower() == 'true'

# SSL/TLS settings
SSL_ENABLED = os.getenv('MI_SSL_ENABLED', 'False').lower() == 'true'
SSL_CERT_PATH = os.getenv('MI_SSL_CERT', '/etc/letsencrypt/live/your-domain/fullchain.pem')
SSL_KEY_PATH = os.getenv('MI_SSL_KEY', '/etc/letsencrypt/live/your-domain/privkey.pem')

# Live monitoring settings
REFRESH_TIME = int(os.getenv('MI_REFRESH_TIME', '10'))
CONNECTION_STRING = os.getenv('MI_CONNECTION_STRING', '')
VERIFIER_CONNECTION_STRING = os.getenv('MI_VERIFIER_CONNECTION_STRING', '') or CONNECTION_STRING
PROGRESS_ENDPOINT_URL = os.getenv('MI_PROGRESS_ENDPOINT_URL', '')

# MongoDB settings
INTERNAL_DB_NAME = os.getenv('MI_INTERNAL_DB_NAME', "mongosync_reserved_for_internal_use")

# UI settings
PLOT_WIDTH = int(os.getenv('MI_PLOT_WIDTH', '1450'))
PLOT_HEIGHT = int(os.getenv('MI_PLOT_HEIGHT', '1800'))
MAX_PARTITIONS_DISPLAY = int(os.getenv('MI_MAX_PARTITIONS_DISPLAY', '10'))

# Error patterns file
ERROR_PATTERNS_FILE = os.getenv('MI_ERROR_PATTERNS_FILE', 
                                 os.path.join(os.path.dirname(__file__), 'error_patterns.json'))

def load_error_patterns():
    """
    Load error patterns from external JSON file.
    
    Returns:
        list: List of dictionaries with 'pattern' and 'friendly_name' keys
    """
    import json
    logger = logging.getLogger(__name__)
    
    try:
        with open(ERROR_PATTERNS_FILE, 'r') as f:
            patterns = json.load(f)
            logger.info(f"Loaded {len(patterns)} error patterns from {ERROR_PATTERNS_FILE}")
            return patterns
    except FileNotFoundError:
        logger.warning(f"Error patterns file not found: {ERROR_PATTERNS_FILE}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in error patterns file: {e}")
        return []
    except Exception as e:
        logger.error(f"Error loading error patterns: {e}")
        return []

def setup_logging():
    """Configure logging based on environment variables."""
    log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        filename=LOG_FILE,
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

def get_app_info():
    """Get application information."""
    return {
        'name': APP_NAME,
        'version': APP_VERSION,
        'log_file': LOG_FILE,
        'host': HOST,
        'port': PORT
    }

def validate_config():
    """Validate configuration on startup."""
    # Check if log file directory is writable
    log_file = Path(LOG_FILE)
    log_dir = log_file.parent
    if not log_dir.exists():
        log_dir.mkdir(parents=True, exist_ok=True)
    
    if not os.access(log_dir, os.W_OK):
        raise PermissionError(f"Cannot write to log directory: {log_dir}")
    
    # Validate port number
    if not (1 <= PORT <= 65535):
        raise ValueError(f"Invalid port number: {PORT}. Must be between 1 and 65535.")
    
    return True

def validate_progress_endpoint_url(url):
    """
    Validate Mongosync Progress Endpoint URL format.
    
    Args:
        url (str): URL to validate in format host:port/api/v1/progress
        
    Returns:
        bool: True if URL matches the expected format
    """
    if not url:
        return False
    pattern = r'^[\w\.\-]+:\d+/api/v1/progress$'
    return bool(re.match(pattern, url))

# Database Connection Management
# Connection pool settings
CONNECTION_POOL_SIZE = int(os.getenv('MI_POOL_SIZE', '10'))
CONNECTION_TIMEOUT_MS = int(os.getenv('MI_TIMEOUT_MS', '5000'))

@lru_cache(maxsize=1)
def get_mongo_client(connection_string):
    """
    Get a cached MongoDB client with connection pooling.
    
    Args:
        connection_string (str): MongoDB connection string
        
    Returns:
        MongoClient: Cached MongoDB client instance
        
    Raises:
        InvalidURI: If the connection string is invalid
        PyMongoError: If connection fails
    """
    logger = logging.getLogger(__name__)
    
    try:
        # Validate connection string format
        from pymongo.uri_parser import parse_uri
        parsed = parse_uri(connection_string)
        
        # Only set tlsCAFile for SRV connections (Atlas) or when TLS is explicitly enabled.
        # Plain mongodb:// URIs to local/on-prem instances often don't use TLS.
        uri_tls_options = parsed.get('options', {})
        is_srv = connection_string.strip().lower().startswith('mongodb+srv://')
        tls_explicitly_set = 'tls' in uri_tls_options or 'ssl' in uri_tls_options
        tls_disabled = uri_tls_options.get('tls', uri_tls_options.get('ssl', True)) is False
        use_tls_ca = is_srv or (tls_explicitly_set and not tls_disabled)

        client_kwargs = dict(
            maxPoolSize=CONNECTION_POOL_SIZE,
            minPoolSize=1,
            maxIdleTimeMS=30000,
            serverSelectionTimeoutMS=CONNECTION_TIMEOUT_MS,
            connectTimeoutMS=CONNECTION_TIMEOUT_MS,
            socketTimeoutMS=CONNECTION_TIMEOUT_MS,
            retryWrites=True,
            retryReads=True,
        )
        if use_tls_ca:
            client_kwargs['tlsCAFile'] = certifi.where()

        # Create client with connection pooling
        client = MongoClient(connection_string, **client_kwargs)
        
        # Test the connection
        client.admin.command('ping')
        logger.info(f"Successfully connected to MongoDB with pool size {CONNECTION_POOL_SIZE}")
        
        return client
        
    except InvalidURI as e:
        logger.error(f"Invalid MongoDB connection string: {e}")
        raise
    except PyMongoError as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error connecting to MongoDB: {e}")
        raise PyMongoError(f"Connection failed: {e}")

def get_database(connection_string, database_name):
    """
    Get a database instance using the cached client.
    
    Args:
        connection_string (str): MongoDB connection string
        database_name (str): Name of the database
        
    Returns:
        Database: MongoDB database instance
    """
    client = get_mongo_client(connection_string)
    return client[database_name]

def validate_connection(connection_string):
    """
    Validate a MongoDB connection string and test connectivity.
    
    Args:
        connection_string (str): MongoDB connection string to validate
        
    Returns:
        bool: True if connection is valid and accessible
        
    Raises:
        InvalidURI: If the connection string format is invalid
        PyMongoError: If connection test fails
    """
    try:
        # This will use the cached client or create a new one
        client = get_mongo_client(connection_string)
        # Test with a simple command
        result = client.admin.command('ping')
        return result.get('ok', 0) == 1
    except Exception as e:
        # Clear the cache if connection fails
        get_mongo_client.cache_clear()
        raise

def clear_connection_cache():
    """
    Clear the connection cache. Useful when connection strings change.
    """
    logger = logging.getLogger(__name__)
    get_mongo_client.cache_clear()
    logger.info("MongoDB connection cache cleared")


# =============================================================================
# In-Memory Session Store
# =============================================================================

# Session settings
SESSION_TIMEOUT = int(os.getenv('MI_SESSION_TIMEOUT', '3600'))  # 1 hour default

class InMemorySessionStore:
    """
    Thread-safe in-memory session store with automatic expiration.
    
    This replaces Flask's built-in session with a simple server-side store.
    Session IDs are stored in cookies, but credentials stay on the server.
    """
    
    def __init__(self, timeout=SESSION_TIMEOUT):
        self._store = {}
        self._lock = threading.Lock()
        self._timeout = timeout
        self._logger = logging.getLogger(__name__)
    
    def create_session(self, data: dict) -> str:
        """
        Create a new session with the given data.
        
        Args:
            data: Dictionary of session data to store
            
        Returns:
            str: Unique session ID
        """
        session_id = str(uuid.uuid4())
        with self._lock:
            self._store[session_id] = {
                'data': data,
                'created_at': time.time(),
                'last_accessed': time.time()
            }
        self._logger.debug(f"Created session: {session_id[:8]}...")
        return session_id
    
    def get_session(self, session_id: str) -> dict:
        """
        Retrieve session data by session ID.
        
        Args:
            session_id: The session ID to look up
            
        Returns:
            dict: Session data, or empty dict if not found/expired
        """
        if not session_id:
            return {}
            
        with self._lock:
            session = self._store.get(session_id)
            if not session:
                return {}
            
            # Check if session has expired
            if time.time() - session['last_accessed'] > self._timeout:
                del self._store[session_id]
                self._logger.debug(f"Session expired: {session_id[:8]}...")
                return {}
            
            # Update last accessed time
            session['last_accessed'] = time.time()
            return session['data'].copy()
    
    def update_session(self, session_id: str, data: dict) -> bool:
        """
        Merge new data into an existing session, preserving unmodified keys.
        
        Args:
            session_id: The session ID to update
            data: New data to merge into the session
            
        Returns:
            bool: True if session was updated, False if not found/expired
        """
        if not session_id:
            return False
            
        with self._lock:
            session = self._store.get(session_id)
            if not session:
                return False
            if time.time() - session['last_accessed'] > self._timeout:
                del self._store[session_id]
                return False
            session['data'].update(data)
            session['last_accessed'] = time.time()
            return True
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.
        
        Args:
            session_id: The session ID to delete
            
        Returns:
            bool: True if session was deleted, False if not found
        """
        if not session_id:
            return False
            
        with self._lock:
            if session_id in self._store:
                del self._store[session_id]
                self._logger.debug(f"Deleted session: {session_id[:8]}...")
                return True
            return False
    
    def cleanup_expired(self):
        """Remove all expired sessions."""
        current_time = time.time()
        with self._lock:
            expired = [
                sid for sid, session in self._store.items()
                if current_time - session['last_accessed'] > self._timeout
            ]
            for sid in expired:
                del self._store[sid]
            if expired:
                self._logger.debug(f"Cleaned up {len(expired)} expired sessions")
    
    def get_active_count(self) -> int:
        """Get the number of active sessions."""
        self.cleanup_expired()
        with self._lock:
            return len(self._store)


# Global session store instance
session_store = InMemorySessionStore()
