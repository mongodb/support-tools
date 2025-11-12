"""
Connection string validation and security module.
Provides comprehensive validation to prevent injection attacks, XSS, and other security threats.
"""
import re
import unicodedata
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from html import escape
from pymongo.uri_parser import parse_uri
from pymongo.errors import InvalidURI

logger = logging.getLogger(__name__)

# Rate limiting storage (in-memory, resets on restart)
_failed_attempts = defaultdict(list)
_lockout_status = {}


class ConnectionValidationError(Exception):
    """Custom exception for connection validation errors."""
    pass


def check_rate_limit(client_ip, max_attempts=5, lockout_minutes=15):
    """
    Check if client has exceeded failed connection attempts.
    
    Args:
        client_ip (str): Client IP address
        max_attempts (int): Maximum failed attempts before lockout
        lockout_minutes (int): Lockout duration in minutes
        
    Raises:
        ConnectionValidationError: If client is rate limited
    """
    now = datetime.now()
    lockout_period = timedelta(minutes=lockout_minutes)
    
    # Check if currently locked out
    if client_ip in _lockout_status:
        lockout_until = _lockout_status[client_ip]
        if now < lockout_until:
            remaining = int((lockout_until - now).total_seconds() / 60)
            logger.warning(f"Rate limit active for {client_ip}, {remaining} minutes remaining")
            raise ConnectionValidationError(
                f"Too many failed attempts. Please try again in {remaining} minutes."
            )
        else:
            # Lockout expired, clear it
            del _lockout_status[client_ip]
            _failed_attempts[client_ip] = []
    
    # Clean old attempts outside lockout window
    _failed_attempts[client_ip] = [
        attempt_time for attempt_time in _failed_attempts[client_ip]
        if now - attempt_time < lockout_period
    ]
    
    # Check if exceeded max attempts
    if len(_failed_attempts[client_ip]) >= max_attempts:
        _lockout_status[client_ip] = now + lockout_period
        logger.warning(f"Rate limit triggered for {client_ip} after {max_attempts} attempts")
        raise ConnectionValidationError(
            f"Too many failed attempts. Please try again in {lockout_minutes} minutes."
        )


def record_failed_attempt(client_ip):
    """
    Record a failed connection attempt for rate limiting.
    
    Args:
        client_ip (str): Client IP address
    """
    _failed_attempts[client_ip].append(datetime.now())
    logger.info(f"Failed attempt recorded for {client_ip} (total: {len(_failed_attempts[client_ip])})")


def clear_rate_limit(client_ip):
    """
    Clear rate limiting for a client after successful validation.
    
    Args:
        client_ip (str): Client IP address
    """
    if client_ip in _failed_attempts:
        del _failed_attempts[client_ip]
    if client_ip in _lockout_status:
        del _lockout_status[client_ip]


def validate_length(connection_string, max_length=2048):
    """
    Validate connection string length to prevent DoS attacks.
    
    Args:
        connection_string (str): Connection string to validate
        max_length (int): Maximum allowed length
        
    Raises:
        ConnectionValidationError: If string is too long
    """
    if len(connection_string) > max_length:
        logger.error(f"Connection string too long: {len(connection_string)} chars")
        raise ConnectionValidationError(
            f"Connection string exceeds maximum allowed length of {max_length} characters."
        )


def validate_uri_scheme(connection_string):
    """
    Validate that connection string uses allowed MongoDB URI schemes.
    
    Args:
        connection_string (str): Connection string to validate
        
    Raises:
        ConnectionValidationError: If scheme is invalid
    """
    allowed_schemes = ['mongodb://', 'mongodb+srv://']
    
    if not any(connection_string.startswith(scheme) for scheme in allowed_schemes):
        logger.error("Invalid URI scheme detected")
        raise ConnectionValidationError(
            "Invalid connection string format. Must start with mongodb:// or mongodb+srv://"
        )


def validate_no_null_bytes(connection_string):
    """
    Prevent null byte injection attacks.
    
    Args:
        connection_string (str): Connection string to validate
        
    Raises:
        ConnectionValidationError: If null bytes detected
    """
    if '\x00' in connection_string or '%00' in connection_string.lower():
        logger.error("Null byte detected in connection string")
        raise ConnectionValidationError("Invalid connection string format.")


def validate_no_crlf(connection_string):
    """
    Prevent CRLF injection attacks that could manipulate logs or HTTP responses.
    
    Args:
        connection_string (str): Connection string to validate
        
    Raises:
        ConnectionValidationError: If CRLF characters detected
    """
    if '\r' in connection_string or '\n' in connection_string:
        logger.error("CRLF characters detected in connection string")
        raise ConnectionValidationError("Invalid connection string format.")
    
    # Check for encoded versions
    if '%0d' in connection_string.lower() or '%0a' in connection_string.lower():
        logger.error("Encoded CRLF detected in connection string")
        raise ConnectionValidationError("Invalid connection string format.")


def validate_allowed_characters(connection_string):
    """
    Ensure connection string only contains valid URI characters.
    Prevents injection attacks and encoding issues.
    
    Args:
        connection_string (str): Connection string to validate
        
    Raises:
        ConnectionValidationError: If invalid characters detected
    """
    # Valid MongoDB URI characters (RFC 3986 + MongoDB specific)
    # Allows: alphanumeric, unreserved chars (- . _ ~), sub-delims (! $ & ' ( ) * + , ; =)
    # percent-encoded chars (%XX), gen-delims (: / ? # [ ] @)
    valid_pattern = re.compile(r'^[A-Za-z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+$')
    
    if not valid_pattern.match(connection_string):
        logger.error("Invalid characters detected in connection string")
        raise ConnectionValidationError(
            "Connection string contains invalid characters. Only standard URI characters are allowed."
        )


def validate_no_html_content(connection_string):
    """
    Detect HTML/script tags that could cause XSS when displayed.
    
    Args:
        connection_string (str): Connection string to validate
        
    Raises:
        ConnectionValidationError: If HTML/script content detected
    """
    dangerous_patterns = [
        r'<script[^>]*>',
        r'<iframe[^>]*>',
        r'<object[^>]*>',
        r'<embed[^>]*>',
        r'<img[^>]*>',
        r'javascript:',
        r'onerror\s*=',
        r'onload\s*=',
        r'<[^>]*on\w+\s*=',  # Any HTML event handler
    ]
    
    connection_string_lower = connection_string.lower()
    for pattern in dangerous_patterns:
        if re.search(pattern, connection_string_lower, re.IGNORECASE):
            logger.error("HTML/script content detected in connection string")
            raise ConnectionValidationError("Invalid connection string format.")


def validate_no_double_encoding(connection_string):
    """
    Prevent double-encoded attacks like %2527 (encoded ').
    
    Args:
        connection_string (str): Connection string to validate
        
    Raises:
        ConnectionValidationError: If double encoding detected
    """
    # Check for double percent encoding (%25 = encoded %)
    if re.search(r'%25[0-9A-Fa-f]{2}', connection_string):
        logger.error("Double encoding detected in connection string")
        raise ConnectionValidationError("Invalid connection string format.")
    
    # Check for unusual encoding patterns
    # MongoDB connection strings shouldn't have these
    suspicious_encoded = ['%00', '%0d', '%0a', '%09', '%22', '%27', '%3c', '%3e']
    for encoded in suspicious_encoded:
        if encoded in connection_string.lower():
            logger.error(f"Suspicious encoded character detected: {encoded}")
            raise ConnectionValidationError("Invalid connection string format.")


def validate_and_normalize_unicode(connection_string):
    """
    Normalize Unicode and detect potential homograph attacks.
    
    Args:
        connection_string (str): Connection string to validate
        
    Returns:
        str: Normalized connection string
        
    Raises:
        ConnectionValidationError: If invalid Unicode or attacks detected
    """
    try:
        # Normalize to NFC form
        normalized = unicodedata.normalize('NFC', connection_string)
        
        # Check if normalization significantly changed the string
        if normalized != connection_string:
            logger.warning("Connection string contains non-normalized Unicode characters")
            raise ConnectionValidationError("Invalid connection string format.")
        
        # Check for right-to-left override characters
        rtl_chars = ['\u202E', '\u202D', '\u202A', '\u202B', '\u202C']
        if any(char in connection_string for char in rtl_chars):
            logger.error("Bidirectional override characters detected")
            raise ConnectionValidationError("Invalid connection string format.")
        
        return normalized
    except ConnectionValidationError:
        raise
    except Exception as e:
        logger.error(f"Unicode validation error: {e}")
        raise ConnectionValidationError("Invalid connection string format.")


def validate_no_path_traversal(connection_string):
    """
    Prevent path traversal patterns that could be used in attacks.
    
    Args:
        connection_string (str): Connection string to validate
        
    Raises:
        ConnectionValidationError: If path traversal patterns detected
    """
    dangerous_patterns = ['../', '..\\', '%2e%2e%2f', '%2e%2e%5c']
    
    connection_string_lower = connection_string.lower()
    for pattern in dangerous_patterns:
        if pattern in connection_string_lower:
            logger.error("Path traversal pattern detected")
            raise ConnectionValidationError("Invalid connection string format.")


def validate_credential_format(connection_string):
    """
    If credentials are present, validate they're in expected format.
    Prevents injection through malformed credentials.
    
    Args:
        connection_string (str): Connection string to validate
        
    Raises:
        ConnectionValidationError: If credentials are malformed
    """
    if '@' in connection_string:
        try:
            # Extract the credentials part (between :// and @)
            parts = connection_string.split('://', 1)
            if len(parts) == 2:
                cred_and_rest = parts[1].split('@', 1)
                if len(cred_and_rest) == 2:
                    credentials = cred_and_rest[0]
                    
                    # Check for suspicious patterns in credentials
                    # Should be username:password format
                    if ':' not in credentials:
                        logger.error("Invalid credential format: missing separator")
                        raise ConnectionValidationError("Invalid connection string format.")
                    
                    username, password = credentials.split(':', 1)
                    
                    # Username and password shouldn't be empty
                    if not username or not password:
                        logger.error("Invalid credential format: empty username or password")
                        raise ConnectionValidationError("Invalid connection string format.")
                    
                    # Check for suspicious characters that might indicate injection
                    # Note: @ is allowed in passwords (encoded), but not raw
                    if '//' in credentials or '<' in credentials or '>' in credentials:
                        logger.error("Suspicious characters in credentials")
                        raise ConnectionValidationError("Invalid connection string format.")
        except ConnectionValidationError:
            raise
        except Exception as e:
            logger.error(f"Credential validation error: {e}")
            raise ConnectionValidationError("Invalid connection string format.")


def validate_connection_string_content(connection_string, config=None):
    """
    Comprehensive connection string content validation.
    Call this BEFORE any parsing or connection attempts.
    
    Args:
        connection_string (str): Connection string to validate
        config (dict): Optional configuration dict with validation toggles
        
    Returns:
        str: Validated and normalized connection string
        
    Raises:
        ConnectionValidationError: If validation fails
    """
    if config is None:
        config = {
            'validate_length': True,
            'validate_scheme': True,
            'validate_charset': True,
            'validate_html': True,
            'validate_encoding': True,
            'validate_unicode': True,
            'validate_credentials': True,
            'validate_path_traversal': True,
            'max_length': 2048
        }
    
    try:
        # 1. Length check (DoS prevention) - must be first
        if config.get('validate_length', True):
            validate_length(connection_string, config.get('max_length', 2048))
        
        # 2. Null byte check - cheap, catches obvious attacks
        validate_no_null_bytes(connection_string)
        
        # 3. CRLF injection check - prevents log injection
        validate_no_crlf(connection_string)
        
        # 4. URI scheme validation - ensures proper MongoDB URI
        if config.get('validate_scheme', True):
            validate_uri_scheme(connection_string)
        
        # 5. Character allowlist - basic injection prevention
        if config.get('validate_charset', True):
            validate_allowed_characters(connection_string)
        
        # 6. HTML/Script content detection - XSS prevention
        if config.get('validate_html', True):
            validate_no_html_content(connection_string)
        
        # 7. Double encoding detection - encoding bypass prevention
        if config.get('validate_encoding', True):
            validate_no_double_encoding(connection_string)
        
        # 8. Path traversal prevention - defense in depth
        if config.get('validate_path_traversal', True):
            validate_no_path_traversal(connection_string)
        
        # 9. Unicode validation and normalization - homograph attack prevention
        if config.get('validate_unicode', True):
            connection_string = validate_and_normalize_unicode(connection_string)
        
        # 10. Credential format validation - ensures proper structure
        if config.get('validate_credentials', True):
            validate_credential_format(connection_string)
        
        logger.info("Connection string passed all content validations")
        return connection_string
        
    except ConnectionValidationError:
        raise
    except Exception as e:
        logger.error(f"Unexpected validation error: {e}")
        raise ConnectionValidationError("Invalid connection string format.")


def sanitize_for_display(connection_string):
    """
    Sanitize connection string for safe HTML display.
    Removes credentials and escapes HTML special characters.
    
    Args:
        connection_string (str): Connection string to sanitize
        
    Returns:
        str: Sanitized string safe for HTML display
    """
    try:
        parsed = parse_uri(connection_string)
        hosts = parsed['nodelist']
        hosts_str = ", ".join([f"{escape(str(host))}:{escape(str(port))}" for host, port in hosts])
        
        # Include database name if present (without credentials)
        database = parsed.get('database', '')
        if database:
            return f"{hosts_str} (database: {escape(database)})"
        return hosts_str
    except Exception as e:
        logger.error(f"Error sanitizing connection string for display: {e}")
        return "[Connection String Provided]"


def validate_required_database(client, required_db_name="mongosync_reserved_for_internal_use"):
    """
    Verify the required internal database exists and is accessible.
    
    Args:
        client: MongoDB client instance
        required_db_name (str): Name of the required database
        
    Raises:
        ConnectionValidationError: If database is missing or inaccessible
    """
    try:
        # Check if the required database exists
        db_list = client.list_database_names()
        if required_db_name not in db_list:
            logger.error(f"Required database '{required_db_name}' not found")
            raise ConnectionValidationError(
                f"Required database not found. This may not be a valid mongosync destination cluster."
            )
        
        # Test read access to the database
        db = client[required_db_name]
        collections = db.list_collection_names()
        
        logger.info(f"Required database '{required_db_name}' validated successfully")
        return True
    except ConnectionValidationError:
        raise
    except Exception as e:
        logger.error(f"Error validating required database: {e}")
        raise ConnectionValidationError(
            "Cannot access required database. Please verify permissions."
        )
