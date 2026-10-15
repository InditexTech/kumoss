<!--
SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)

SPDX-License-Identifier: Apache-2.0
-->

# SearxNG Deployment

This repository contains a Docker setup for deploying SearxNG with JSON API support enabled, bundled with the Kumoss stack as the agents' web-search backend.

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

### Using the Kumoss docker-compose (Recommended)

1. **Set the secret key** in the service's `.env` file:

   ```bash
   cp services/searxng/env.sample services/searxng/.env
   # then edit SEARXNG_SECRET, e.g. the value of `openssl rand -base64 32`
   ```

   The container entrypoint substitutes `SEARXNG_SECRET` into
   `settings.yml`'s `server.secret_key` at start. Leaving it unset makes
   the container generate a random key at every start — acceptable for a
   throwaway local stack, never for a reachable deployment.

2. **Start the service**:
   ```bash
   docker compose up -d searxng
   ```

3. **Access SearxNG**:

   The Compose service uses `expose` rather than `ports`, so the engine
   is reachable only inside the `bridge-network` Docker network — the
   core calls it at `http://searxng:8888`, and nothing is published on
   the host. To reach it from the host (your machine), either publish
   the port by overriding the service:

   ```yaml
   # docker-compose.override.yml
   services:
     searxng:
       ports:
         - "8888:8888"
   ```

   …or verify it from inside the network:

   ```bash
   docker exec kumoss-core-1 python -c \
     "import httpx; print(httpx.get('http://searxng:8888/search?q=test&format=json', timeout=15).status_code)"
   ```

   With the port published, the Web UI is at http://localhost:8888 and
   the JSON API at http://localhost:8888/search?q=your_query&format=json.

### Using Docker

1. **Build the image**:
   ```bash
   docker build -t searxng-custom services/searxng
   ```

2. **Run the container** (this publishes the port on the host):
   ```bash
   docker run -d \
     -p 8888:8888 \
     -v $(pwd)/services/searxng/settings.yml:/etc/searxng/settings.yml:ro \
     -e SEARXNG_BASE_URL=http://localhost:8888 \
     -e SEARXNG_SECRET=your_random_secret_key_here \
     --name searxng \
     searxng-custom
   ```

## API Usage

Once running, query the JSON API — from the host when the port is
published (as in the standalone `docker run` above), otherwise from a
container on the same network:

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
- **Pinned SearXNG base image**: SearXNG is a rolling release — every
  master commit is a release, so `:latest` would silently change at each
  rebuild. The Dockerfile pins a datetagged build (currently
  `searxng/searxng:2026.10.13-22c64b8d3`) that this service was validated
  against. Bumping is deliberate:

  ```bash
  docker pull searxng/searxng:latest          # see which version is current
  # update the FROM tag in services/searxng/Dockerfile to match, then:
  docker compose build searxng && docker compose up -d searxng
  # verify: the banner at `docker compose logs searxng` prints the new
  # version and `docker exec kumoss-core-1 python -c "import httpx; \
  # print(httpx.get('http://searxng:8888/search?q=test&format=json', timeout=15).status_code)"`
  # returns 200.
  ```

## Stopping the Service

```bash
docker compose down searxng
```

## Logs

```bash
docker compose logs -f searxng
```
