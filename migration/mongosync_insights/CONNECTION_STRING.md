# Connection String Guide

This document covers connection string best practices, security considerations, and troubleshooting for Mongosync Insights.

## Connection String Formats

### MongoDB Atlas (SRV)

Use the SRV connection string format:

```
mongodb+srv://username:password@cluster.mongodb.net/
```

### Standard Connection String

```
mongodb://username:password@host1:27017,host2:27017/
```

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
mongodb://user:p%40ss%3Aword@cluster.mongodb.net/
```

## Using Environment Variables

For production, store the connection string in an environment variable to avoid entering it through the web UI:

```bash
export MI_CONNECTION_STRING="mongodb+srv://user:pass@cluster.mongodb.net/"
python3 mongosync_insights.py
```

See [CONFIGURATION.md](CONFIGURATION.md) for all available connection-related environment variables.

## Security Considerations

- **Credentials are never displayed:** Connection strings are sanitized before display in the UI -- only host, port, and database name are shown
- **Credentials are never logged:** Connection strings with passwords are not written to log files
- **HTTPS recommended:** For production deployments, always use HTTPS to protect connection strings in transit. See [HTTPS_SETUP.md](HTTPS_SETUP.md)
- **Secure cookies:** Enable `MI_SECURE_COOKIES=true` when using HTTPS to ensure session cookies are only transmitted over encrypted connections

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

1. Check for network timeouts (default: 5 seconds, configurable via `MI_TIMEOUT_MS`)
2. Verify DNS resolution for hostname
3. Ensure no proxy blocking MongoDB traffic

### General Steps

1. Check logs: `insights.log`
2. Verify connection string format
3. Test connection using MongoDB shell or Compass
4. Review MongoDB server logs for authentication failures

## Related Documentation

- **[README.md](README.md)** - Getting started and installation guide
- **[CONFIGURATION.md](CONFIGURATION.md)** - Complete environment variables reference
- **[HTTPS_SETUP.md](HTTPS_SETUP.md)** - Enable HTTPS/SSL for secure deployments

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
