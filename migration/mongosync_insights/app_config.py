"""
Configuration management for Mongosync Insights.
Supports environment variables and configurable paths.
"""
import os
import logging
from pathlib import Path
from functools import lru_cache
from pymongo import MongoClient
from pymongo.errors import PyMongoError, InvalidURI

# Environment variable configuration
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('MI_LOG_FILE', 'insights.log')
HOST = os.getenv('MI_HOST', '127.0.0.1')
PORT = int(os.getenv('MI_PORT', '3030'))

# Application constants
APP_NAME = "Mongosync Insights"
APP_VERSION = "0.7.0.16"

# File upload settings
MAX_FILE_SIZE = int(os.getenv('MI_MAX_FILE_SIZE', str(10 * 1024 * 1024 * 1024)))  # 10GB default
ALLOWED_EXTENSIONS = {'.log', '.json', '.out'}
ALLOWED_MIME_TYPES = ['application/x-ndjson']

# Security settings
SECURE_COOKIES = os.getenv('MI_SECURE_COOKIES', 'True').lower() == 'true'

# SSL/TLS settings
SSL_ENABLED = os.getenv('MI_SSL_ENABLED', 'False').lower() == 'true'
SSL_CERT_PATH = os.getenv('MI_SSL_CERT', '/etc/letsencrypt/live/your-domain/fullchain.pem')
SSL_KEY_PATH = os.getenv('MI_SSL_KEY', '/etc/letsencrypt/live/your-domain/privkey.pem')

# Live monitoring settings
REFRESH_TIME = int(os.getenv('MI_REFRESH_TIME', '10'))
CONNECTION_STRING = os.getenv('MI_CONNECTION_STRING', '')

# MongoDB settings
INTERNAL_DB_NAME = os.getenv('MI_INTERNAL_DB_NAME', "mongosync_reserved_for_internal_use")

# UI settings
PLOT_WIDTH = int(os.getenv('MI_PLOT_WIDTH', '1450'))
PLOT_HEIGHT = int(os.getenv('MI_PLOT_HEIGHT', '1800'))
MAX_PARTITIONS_DISPLAY = int(os.getenv('MI_MAX_PARTITIONS_DISPLAY', '10'))

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
        parse_uri(connection_string)
        
        # Create client with connection pooling
        client = MongoClient(
            connection_string,
            maxPoolSize=CONNECTION_POOL_SIZE,
            minPoolSize=1,
            maxIdleTimeMS=30000,  # 30 seconds
            serverSelectionTimeoutMS=CONNECTION_TIMEOUT_MS,
            connectTimeoutMS=CONNECTION_TIMEOUT_MS,
            socketTimeoutMS=CONNECTION_TIMEOUT_MS,
            retryWrites=True,
            retryReads=True
        )
        
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
