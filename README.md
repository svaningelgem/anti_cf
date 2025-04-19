# anti-cf

A Python library for handling Cloudflare-protected websites using FlareSolverr.

## Overview

`anti-cf` provides a persistent session wrapper for handling websites protected by Cloudflare's anti-bot measures. It automatically manages cookies, user agents, and integrates with FlareSolverr to bypass Cloudflare challenges.

## Features

- Persistent cookie storage
- Automatic FlareSolverr management (including Docker startup)
- Optional request caching via `requests-cache`
- Random user agent generation
- Transparent handling of Cloudflare challenges

## Installation

```bash
pip install anti-cf
```

## Usage

### Basic Usage

```python
from anti_cf import session

# The library will automatically check if FlareSolverr is running
# and start it if needed using Docker

# For Cloudflare-protected sites
response = session.get("https://cloudflare-protected-site.com", try_with_cloudflare=True)

# For regular requests
response = session.get("https://example.com")
```

### Advanced Usage

```python
from anti_cf import session

# Set a custom user agent
session.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

# Post requests work as normal
response = session.post("https://example.com/api", json={"key": "value"})

# All cookies are automatically saved between requests
```

### Error Handling

```python
from anti_cf import session
from requests import HTTPError

try:
    response = session.get("https://cloudflare-protected-site.com", try_with_cloudflare=True)
    response.raise_for_status()
except HTTPError as e:
    print(f"HTTP error occurred: {e}")
```

## Dependencies

- Python 3.11+
- FlareSolverr
- Docker (optional, for automatic FlareSolverr startup)
- `requests` or `requests-cache` (optional for caching)
- `fake-useragent`
- `logprise`

## Configuration

The library uses the following default settings:
- Cache directory: `~/.cache/anti_cf/`
- FlareSolverr API: `http://localhost:8191/`
- Default timeout: 600 seconds
- Cache expiry: 2 hours (when using `requests-cache`)

## How It Works

1. When making a request to a Cloudflare-protected site:
    - First attempts a normal request
    - If Cloudflare challenge detected, sends the request through FlareSolverr
    - Stores the resulting cookies for future requests

2. On startup:
    - Checks if FlareSolverr API is reachable
    - If not available, automatically starts the Docker container

## Docker

By default, `anti-cf` will attempt to start the FlareSolverr Docker container:

```
ghcr.io/svaningelgem/flaresolverr:latest
```

## License

Copyright © Steven Van Ingelgem <steven@vaningelgem.be>