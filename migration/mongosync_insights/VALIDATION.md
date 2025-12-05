# Connection String Validation

This document describes the connection string handling in Mongosync Insights.

## Overview

Mongosync Insights uses PyMongo's built-in validation for connection strings, which provides:
- URI format validation
- Connection testing
- Authentication verification

## Validation Process

### 1. Empty String Check

The application first checks if a connection string was provided:

```python
if not TARGET_MONGO_URI or not TARGET_MONGO_URI.strip():
    return error("Please provide a valid MongoDB connection string.")
```

### 2. PyMongo URI Parsing

PyMongo's `parse_uri()` function validates the connection string format and raises `InvalidURI` if the format is invalid. This checks:
- Proper URI scheme (`mongodb://` or `mongodb+srv://`)
- Valid URI syntax
- Proper host and port format
- Valid URI components

### 3. Connection Test

The application attempts to connect to MongoDB using `validate_connection()`, which:
- Creates a MongoDB client
- Tests connectivity with a `ping` command
- Validates authentication credentials
- Raises `PyMongoError` if connection fails

## Display Sanitization

Connection strings are sanitized before display to protect credentials.

### `sanitize_for_display(connection_string)`

This function removes credentials from connection strings for safe display in the UI.

**Example:**
```python
# Input
connection_string = "mongodb+srv://user:password@cluster.mongodb.net/mydb"

# Output
sanitized = "cluster.mongodb.net:27017 (database: mydb)"
```

**Implementation:**
- Parses the connection string to extract hosts and database
- Escapes HTML special characters
- Returns only non-sensitive information
- Returns `"[Connection String Provided]"` if parsing fails

## Error Handling

The application provides clear error messages for common issues:

### Invalid URI Format
**Error Title:** "Invalid Connection String"  
**Error Message:** "The connection string format is invalid. Please check your MongoDB connection string and try again."

**Common causes:**
- Incorrect URI scheme
- Missing required components
- Invalid characters in URI

### Connection Failed
**Error Title:** "Connection Failed"  
**Error Message:** "Could not connect to MongoDB. Please verify your credentials, network connectivity, and that the cluster is accessible."

**Common causes:**
- Incorrect username or password
- Network connectivity issues
- Firewall blocking connection
- MongoDB server not running
- Incorrect host or port

### Unexpected Error
**Error Title:** "Connection Error"  
**Error Message:** "An unexpected error occurred. Please try again."

**Common causes:**
- Timeout issues
- DNS resolution failures
- Unexpected server responses

## Logging

All connection attempts and errors are logged to `insights.log`:

```
logger.error(f"Invalid connection string format: {e}")
logger.error(f"Failed to connect: {e}")
logger.error(f"Unexpected error during connection validation: {e}")
```

**Note:** Connection strings with credentials are not logged to prevent credential exposure.

## Security Considerations

### Credential Protection

1. **Never displayed:** Credentials are always removed before displaying connection information
2. **Not logged:** Connection strings with passwords are never written to logs
3. **Sanitized output:** Only host, port, and database name are shown in the UI

### HTTPS Recommended

For production deployments, always use HTTPS to protect connection strings in transit. See [HTTPS_SETUP.md](HTTPS_SETUP.md) for setup instructions.

### Secure Cookies

Enable secure cookies when using HTTPS:

```bash
MI_SECURE_COOKIES=true
```

This ensures session cookies are only transmitted over encrypted connections.

## Connection String Best Practices

### MongoDB Atlas

Use the SRV connection string format:

```
mongodb+srv://username:password@cluster.mongodb.net/database
```

### Credentials in Environment Variables

For production, store the connection string in an environment variable:

```bash
export MI_CONNECTION_STRING="mongodb+srv://user:pass@cluster.mongodb.net/db"
python3 mongosync_insights.py
```

This prevents credentials from being entered through the web UI.

### URL Encoding

Special characters in passwords must be URL-encoded:

- `@` becomes `%40`
- `:` becomes `%3A`
- `/` becomes `%2F`
- `?` becomes `%3F`
- `#` becomes `%23`

Example:
```
# Password: p@ss:word
mongodb://user:p%40ss%3Aword@cluster.mongodb.net/db
```

## Troubleshooting

### "Invalid Connection String" Error

1. Check the URI format starts with `mongodb://` or `mongodb+srv://`
2. Verify all components are properly formatted
3. Ensure special characters in password are URL-encoded
4. Check for typos in the connection string

### "Connection Failed" Error

1. Verify credentials are correct
2. Check network connectivity to MongoDB server
3. Ensure MongoDB server is running
4. Verify firewall allows outbound connections on MongoDB port
5. For Atlas, ensure IP address is whitelisted

### Connection Hangs

1. Check for network timeouts (default: 5 seconds)
2. Verify DNS resolution for hostname
3. Ensure no proxy blocking MongoDB traffic

## Support

For connection issues:

1. Check logs: `insights.log`
2. Verify connection string format
3. Test connection using MongoDB shell or Compass
4. Review MongoDB server logs for authentication failures
