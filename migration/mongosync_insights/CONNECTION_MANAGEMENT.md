# Database Connection Management

## Overview

The Mongosync Insights application uses a centralized database connection management system with connection pooling and caching to improve performance and resource utilization.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MI_POOL_SIZE` | `10` | Maximum number of connections in the pool |
| `MONGOSYNC_TIMEOUT_MS` | `5000` | Connection timeout in milliseconds |

### Connection Pool Settings

```python
# Connection pool configuration
CONNECTION_POOL_SIZE = int(os.getenv('MI_POOL_SIZE', '10'))
CONNECTION_TIMEOUT_MS = int(os.getenv('MONGOSYNC_TIMEOUT_MS', '5000'))
```

## Security Considerations

- Connection strings are cached in memory - ensure proper application security
- Use secure connection strings with authentication
- Consider connection string rotation in production environments
- Monitor connection pool usage to prevent resource exhaustion
