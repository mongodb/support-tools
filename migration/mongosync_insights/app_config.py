"""
Configuration management for Mongosync Insights.
Supports environment variables and configurable paths.
"""
import os
import logging
from pathlib import Path
import configparser

# Environment variable configuration
CONFIG_PATH = os.getenv('MONGOSYNC_CONFIG', 'config.ini')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('MONGOSYNC_LOG_FILE', 'insights.log')
HOST = os.getenv('MONGOSYNC_HOST', '0.0.0.0')
PORT = int(os.getenv('MONGOSYNC_PORT', '3030'))

# Application constants
APP_NAME = "Mongosync Insights"
APP_VERSION = "0.6.9.2"

# File upload settings
MAX_FILE_SIZE = int(os.getenv('MONGOSYNC_MAX_FILE_SIZE', str(10 * 1024 * 1024 * 1024)))  # 10GB default
ALLOWED_EXTENSIONS = {'.log', '.json', '.out'}

# Live monitoring settings
REFRESH_TIME = int(os.getenv('MONGOSYNC_REFRESH_TIME', '10'))

# MongoDB settings
INTERNAL_DB_NAME = os.getenv('MONGOSYNC_INTERNAL_DB_NAME', "mongosync_reserved_for_internal_use")

# UI settings
PLOT_WIDTH = int(os.getenv('MONGOSYNC_PLOT_WIDTH', '1450'))
PLOT_HEIGHT = int(os.getenv('MONGOSYNC_PLOT_HEIGHT', '1800'))
MAX_PARTITIONS_DISPLAY = int(os.getenv('MONGOSYNC_MAX_PARTITIONS_DISPLAY', '10'))

def setup_logging():
    """Configure logging based on environment variables."""
    log_level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        filename=LOG_FILE,
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

def load_config():
    """Load configuration from file with environment variable support."""
    config = configparser.ConfigParser()
    
    # Check if config file exists
    config_file = Path(CONFIG_PATH)
    if not config_file.exists():
        # Create default config file if it doesn't exist
        create_default_config(config_file)
    
    config.read(CONFIG_PATH)
    
    # Override with environment variables if they exist
    if 'LiveMonitor' not in config:
        config.add_section('LiveMonitor')
    
    # Allow environment variables to override config file values
    config['LiveMonitor']['connectionString'] = os.getenv(
        'MONGOSYNC_CONNECTION_STRING', 
        config.get('LiveMonitor', 'connectionString', fallback='')
    )
    config['LiveMonitor']['refreshTime'] = os.getenv(
        'MONGOSYNC_REFRESH_TIME',
        config.get('LiveMonitor', 'refreshTime', fallback='10')
    )
    
    return config

def create_default_config(config_file):
    """Create a default configuration file."""
    config = configparser.ConfigParser()
    config.add_section('LiveMonitor')
    config['LiveMonitor']['connectionString'] = ''
    config['LiveMonitor']['refreshTime'] = '10'
    
    with open(config_file, 'w') as f:
        config.write(f)
    
    print(f"Created default configuration file: {config_file}")

def save_config(config):
    """Save configuration to file."""
    with open(CONFIG_PATH, 'w') as f:
        config.write(f)

def get_app_info():
    """Get application information."""
    return {
        'name': APP_NAME,
        'version': APP_VERSION,
        'config_path': CONFIG_PATH,
        'log_file': LOG_FILE,
        'host': HOST,
        'port': PORT
    }

def validate_config():
    """Validate configuration on startup."""
    config_file = Path(CONFIG_PATH)
    
    # Check if config file is readable
    if config_file.exists() and not os.access(config_file, os.R_OK):
        raise PermissionError(f"Cannot read configuration file: {CONFIG_PATH}")
    
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
