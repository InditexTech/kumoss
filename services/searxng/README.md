<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# SearxNG Deployment

This repository contains a Docker setup for deploying SearxNG with JSON API support enabled.

## Features

- SearxNG metasearch engine
- JSON API format enabled (in addition to HTML)
- Docker and Docker Compose setup
- Easy to deploy and customize

## Configuration

The `settings.yml` file includes the necessary configuration to enable JSON API responses:

```yaml
search:
  formats:
    - html
    - json
```

## Quick Start

### Using Docker Compose (Recommended)

1. **Set the secret key** in the service's `.env` file:

   ```bash
   cp services/searxng/env.sample services/searxng/.env
   # then edit SEARXNG_SECRET, e.g. the value of `openssl rand -base64 32`
   ```

   The container entrypoint substitutes `SEARXNG_SECRET` into
   `settings.yml`'s `server.secret_key` at start. Leaving it unset makes
   the container fall back to a public example key — acceptable for a
   throwaway local stack, never for a reachable deployment.

2. **Start the service**:
   ```bash
   docker-compose up -d
   ```

3. **Access SearxNG**:
   - Web UI: http://localhost:8888
   - JSON API: http://localhost:8888/search?q=your_query&format=json

### Using Docker

1. **Build the image**:
   ```bash
   docker build -t searxng-custom .
   ```

2. **Run the container**:
   ```bash
   docker run -d \
     -p 8888:8888 \
     -v $(pwd)/settings.yml:/etc/searxng/settings.yml:ro \
     -e SEARXNG_BASE_URL=http://localhost:8888 \
     -e SEARXNG_SECRET=your_random_secret_key_here \
     --name searxng \
     searxng-custom
   ```

## API Usage

Once running, you can query the JSON API:

```bash
# Simple search
curl "http://localhost:8888/search?q=test&format=json"

# Search with category filter
curl "http://localhost:8888/search?q=test&format=json&categories=general"

# Search with language
curl "http://localhost:8888/search?q=test&format=json&language=en"
```

## Customization

Edit `settings.yml` to customize:
- Search engines
- UI preferences
- Security settings
- Rate limiting
- And more...

Refer to the [SearxNG documentation](https://docs.searxng.org/) for all available options.

## Important Notes

- **Change the secret key** via `services/searxng/.env` (`SEARXNG_SECRET`) before deploying to production
- The `limiter` is disabled by default - enable it for production use
- Image proxy is enabled for privacy
- **Corporate proxy TLS**: the Dockerfile pulls the certificates from the
  host's `/usr/local/share/ca-certificates/` at build time (via the
  `host-certs` additional build context in docker-compose.yml) and trusts
  them with `update-ca-certificates`, so outbound HTTPS works behind the
  SSL-inspecting proxy. Update the host folder if the corporate CA changes.

## Stopping the Service

```bash
docker-compose down
```

## Logs

```bash
docker-compose logs -f searxng
```

