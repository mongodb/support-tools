# Connection String Validation

This document describes the security validations implemented for MongoDB connection strings in Mongosync Insights.

## Overview

The application implements comprehensive, multi-layered validation to protect against various security threats including:
- Injection attacks (SQL, NoSQL, command injection)
- Cross-Site Scripting (XSS)
- Log injection
- Brute force attacks
- Encoding bypass attacks
- Homograph attacks

## Validation Layers

### 1. Rate Limiting

Prevents brute force attacks by limiting failed connection attempts.

**Configuration:**
```bash
MI_MAX_FAILED_ATTEMPTS=5          # Maximum failed attempts before lockout
MI_LOCKOUT_MINUTES=15             # Lockout duration in minutes
```

**Behavior:**
- Tracks failed attempts per client IP address
- Locks out clients after exceeding maximum attempts
- Automatically expires lockouts after configured duration
- Clears rate limit on successful validation

### 2. Length Validation

Prevents Denial of Service (DoS) attacks using extremely long connection strings.

**Configuration:**
```bash
MI_MAX_CONNECTION_LENGTH=2048     # Maximum connection string length in characters
MI_VALIDATE_LENGTH=true           # Enable/disable length validation
```

**Checks:**
- Connection string does not exceed maximum length

### 3. URI Scheme Validation

Ensures only legitimate MongoDB URI schemes are used.

**Configuration:**
```bash
MI_VALIDATE_SCHEME=true           # Enable/disable scheme validation
```

**Allowed schemes:**
- `mongodb://` - Standard MongoDB connection
- `mongodb+srv://` - MongoDB Atlas/DNS SRV connection

**Blocks:**
- HTTP, HTTPS, FTP, and other non-MongoDB schemes

### 4. Null Byte Prevention

Prevents null byte injection attacks that can truncate strings and bypass security checks.

**Configuration:**
- Always enabled (critical security check)

**Blocks:**
- Raw null bytes (`\x00`)
- URL-encoded null bytes (`%00`)

### 5. CRLF Injection Prevention

Prevents Carriage Return Line Feed (CRLF) injection that could manipulate logs or HTTP responses.

**Configuration:**
- Always enabled (critical security check)

**Blocks:**
- Raw CRLF characters (`\r`, `\n`)
- URL-encoded CRLF (`%0d`, `%0a`)

### 6. Character Allowlist

Restricts connection strings to valid URI characters, preventing various injection attacks.

**Configuration:**
```bash
MI_VALIDATE_CHARSET=true          # Enable/disable character validation
```

**Allowed characters:**
- Alphanumeric: `A-Z`, `a-z`, `0-9`
- Unreserved: `-`, `.`, `_`, `~`
- Sub-delimiters: `!`, `$`, `&`, `'`, `(`, `)`, `*`, `+`, `,`, `;`, `=`
- Gen-delimiters: `:`, `/`, `?`, `#`, `[`, `]`, `@`
- Percent-encoded: `%XX`

**Blocks:**
- Control characters
- Shell metacharacters
- Script injection characters

### 7. HTML/Script Detection

Detects and blocks HTML and JavaScript content that could cause XSS when displayed.

**Configuration:**
```bash
MI_VALIDATE_HTML=true             # Enable/disable HTML detection
```

**Blocks:**
- `<script>` tags
- `<iframe>`, `<object>`, `<embed>` tags
- `<img>` tags
- `javascript:` URIs
- HTML event handlers (`onerror`, `onload`, etc.)

### 8. Double Encoding Prevention

Prevents double-encoding attacks that could bypass other validations.

**Configuration:**
```bash
MI_VALIDATE_ENCODING=true         # Enable/disable encoding validation
```

**Blocks:**
- Double percent-encoding (e.g., `%2527` for encoded `'`)
- Suspicious encoded characters (`%00`, `%0d`, `%0a`, `%22`, `%27`, `%3c`, `%3e`)

### 9. Unicode Normalization

Normalizes Unicode and prevents homograph attacks using lookalike characters.

**Configuration:**
```bash
MI_VALIDATE_UNICODE=true          # Enable/disable Unicode validation
```

**Checks:**
- Normalizes to NFC (Canonical Decomposition, followed by Canonical Composition)
- Rejects non-normalized strings
- Blocks bidirectional override characters (used in spoofing attacks)

**Blocks:**
- Right-to-left override (`\u202E`)
- Other bidirectional control characters

### 10. Path Traversal Prevention

Prevents path traversal patterns that could be exploited in unexpected code paths.

**Configuration:**
```bash
MI_VALIDATE_PATH_TRAVERSAL=true   # Enable/disable path traversal validation
```

**Blocks:**
- `../` patterns
- `..\\` patterns
- Encoded versions (`%2e%2e%2f`, `%2e%2e%5c`)

### 11. Credential Format Validation

Ensures credentials are properly formatted when present.

**Configuration:**
```bash
MI_VALIDATE_CREDENTIALS=true      # Enable/disable credential validation
```

**Checks:**
- Credentials follow `username:password` format
- Neither username nor password is empty
- No suspicious characters in credentials

### 12. Required Database Validation

Verifies the required mongosync internal database exists and is accessible.

**Configuration:**
```bash
MI_VALIDATE_REQUIRED_DB=true      # Enable/disable database validation
MI_INTERNAL_DB_NAME=mongosync_reserved_for_internal_use  # Required database name
```

**Checks:**
- Database exists on the cluster
- Database is accessible (read permissions)
- Collections can be listed

## Validation Order

Validations are executed in the following order (optimized for performance):

1. **Length check** - Quick, prevents processing oversized strings
2. **Null byte check** - Simple, catches obvious attacks
3. **CRLF check** - Simple, prevents log injection
4. **URI scheme validation** - Ensures proper MongoDB URI
5. **Character allowlist** - Broad injection prevention
6. **HTML/script detection** - XSS prevention
7. **Double encoding detection** - Encoding bypass prevention
8. **Path traversal prevention** - Defense in depth
9. **Unicode normalization** - Homograph attack prevention (expensive)
10. **Credential format validation** - Structure validation
11. **Connection test** - Network and authentication (expensive)
12. **Required database validation** - Application-specific check

## Error Handling

### Generic Error Messages

To prevent information leakage, validation errors return generic messages to users:

- **Validation Error**: "Invalid connection string format."
- **Rate Limit**: "Too many failed attempts. Please try again in X minutes."
- **Connection Failed**: "Could not connect to MongoDB. Please verify your credentials and network connectivity."

### Detailed Logging

Specific error details are logged for administrators:

```
logger.error(f"CRLF characters detected in connection string")
logger.error(f"Rate limit triggered for {client_ip} after {max_attempts} attempts")
logger.error(f"Invalid credential format: missing separator")
```

## Testing

Run the validation test suite:

```bash
cd migration/mongosync_insights
python3 test_validations.py
```

The test suite validates:
- All individual validation functions
- Comprehensive validation chain
- Common attack vectors (XSS, SQL injection, CRLF, etc.)

## Security Best Practices

### Always Enable

The following validations should **always** be enabled:
- Null byte prevention (always enabled)
- CRLF prevention (always enabled)
- Character allowlist
- HTML/script detection
- Double encoding prevention

### Production Deployment

For production deployments, ensure:

1. **All validations enabled**:
   ```bash
   MI_VALIDATE_LENGTH=true
   MI_VALIDATE_SCHEME=true
   MI_VALIDATE_CHARSET=true
   MI_VALIDATE_HTML=true
   MI_VALIDATE_ENCODING=true
   MI_VALIDATE_UNICODE=true
   MI_VALIDATE_CREDENTIALS=true
   MI_VALIDATE_PATH_TRAVERSAL=true
   MI_VALIDATE_REQUIRED_DB=true
   ```

2. **Strict rate limiting**:
   ```bash
   MI_MAX_FAILED_ATTEMPTS=5
   MI_LOCKOUT_MINUTES=15
   ```

3. **HTTPS enabled** (see HTTPS_SETUP.md)

4. **Secure cookies enabled**:
   ```bash
   MI_SECURE_COOKIES=true
   ```

### Development/Testing

For local development, you can disable specific validations if needed:

```bash
# Example: Disable unicode validation for testing
MI_VALIDATE_UNICODE=false

# Example: Increase max length for testing large connection strings
MI_MAX_CONNECTION_LENGTH=4096
```

**Warning**: Never disable critical validations (null bytes, CRLF) even in development.

## Configuration Reference

All validation environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_MAX_CONNECTION_LENGTH` | `2048` | Maximum connection string length |
| `MI_MAX_FAILED_ATTEMPTS` | `5` | Failed attempts before lockout |
| `MI_LOCKOUT_MINUTES` | `15` | Lockout duration in minutes |
| `MI_VALIDATE_LENGTH` | `true` | Enable length validation |
| `MI_VALIDATE_SCHEME` | `true` | Enable URI scheme validation |
| `MI_VALIDATE_CHARSET` | `true` | Enable character allowlist |
| `MI_VALIDATE_HTML` | `true` | Enable HTML/script detection |
| `MI_VALIDATE_ENCODING` | `true` | Enable double encoding detection |
| `MI_VALIDATE_UNICODE` | `true` | Enable Unicode normalization |
| `MI_VALIDATE_CREDENTIALS` | `true` | Enable credential format validation |
| `MI_VALIDATE_PATH_TRAVERSAL` | `true` | Enable path traversal prevention |
| `MI_VALIDATE_REQUIRED_DB` | `true` | Enable required database validation |
| `MI_INTERNAL_DB_NAME` | `mongosync_reserved_for_internal_use` | Required database name |

## Attack Vector Examples

### Blocked Attacks

The validation system blocks these common attack vectors:

1. **XSS Attack**:
   ```
   mongodb+srv://user:pass<script>alert(1)</script>@test.mongodb.net/db
   ```

2. **SQL Injection**:
   ```
   mongodb://user'; DROP TABLE users--@localhost/db
   ```

3. **CRLF Injection**:
   ```
   mongodb://user:pass@localhost/db\r\nInjected: header
   ```

4. **Path Traversal**:
   ```
   mongodb://user:pass@localhost/../../../etc/passwd
   ```

5. **Null Byte Injection**:
   ```
   mongodb://user:pass\x00@localhost/db
   ```

6. **Double Encoding**:
   ```
   mongodb://test%2527%2520OR%25201=1@localhost
   ```

7. **Homograph Attack**:
   ```
   mongodb://user:pass@mоngodb.net  # Cyrillic 'o' instead of Latin 'o'
   ```

## Support

For questions or issues with validation:

1. Check logs: `insights.log`
2. Run test suite: `python3 test_validations.py`
3. Review configuration: ensure all required environment variables are set
4. Contact support with sanitized log entries (never include connection strings with credentials)

### License

[Apache 2.0](http://www.apache.org/licenses/LICENSE-2.0)

DISCLAIMER
----------
Please note: all tools/ scripts in this repo are released for use "AS IS" **without any warranties of any kind**,
including, but not limited to their installation, use, or performance.  We disclaim any and all warranties, either 
express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness 
for a particular purpose.  We do not warrant that the technology will meet your requirements, that the operation 
thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**.  There is no guarantee that they have been through 
thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with 
their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing 
environment.

Thanks,  
The MongoDB Support Team