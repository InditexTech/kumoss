FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

FROM python:3.14-bookworm@sha256:7ee7e4d4fb42c3ad45b8fdc473b64ec69c3cf6e80ae5d52f6fa55f77fac29027

# Minimal apt deps the core actually uses at runtime: git for cloning user
# repos, ripgrep for the workspace inspection tools, curl for general use,
# libnss3-tools for importing the corporate roots into Chromium's NSS
# database in the page-read step below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ripgrep libnss3-tools \
    && rm -rf /var/lib/apt/lists/*

# Corporate CA certs via an additional build context (docker-compose.yml:
# build.additional_contexts), so the repo holds no local copies. Build-time
# HTTPS — the Python index and the Chromium download below — must anchor
# the MITM proxy's re-signed chain.
COPY --from=host-certs / /usr/local/share/ca-certificates/
RUN update-ca-certificates

# Unprivileged runtime identity. The uid/gid MUST match the iac image's
# (same ARG names and defaults in services/iac/Dockerfile): both
# containers share the `workspaces` volume read-write, and the IaC
# engine must be able to write lock, plan and state files into the
# clones the core creates.
ARG KUMOSS_UID=10001
ARG KUMOSS_GID=10001
RUN groupadd --gid "${KUMOSS_GID}" kumoss \
    && useradd --uid "${KUMOSS_UID}" --gid "${KUMOSS_GID}" \
        --create-home --home-dir /home/kumoss --shell /usr/sbin/nologin kumoss \
    && mkdir -p /workspaces && chown kumoss:kumoss /workspaces

# config.yaml
COPY config.yaml /etc/kumoss/

COPY --from=uv /uv /uvx /bin/

WORKDIR /usr/src/app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CONCURRENT_DOWNLOADS=4 \
    PATH="/usr/src/app/.venv/bin:$PATH" \
    HOME=/home/kumoss

COPY core/pyproject.toml core/uv.lock ./

RUN uv sync --locked --no-install-project --no-default-groups

# Headless Chromium for the `web_search` page reads. Installed system-wide
# so the unprivileged runtime user finds it; PLAYWRIGHT_AUTO_INSTALL=false
# stops a first-use download at request time. The downloader is Node-based
# and reads the system bundle only through NODE_EXTRA_CA_CERTS.
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/ms-playwright \
    PLAYWRIGHT_AUTO_INSTALL=false \
    NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
RUN uv run playwright install --with-deps chromium \
    && chmod -R a+rX /usr/local/share/ms-playwright

# Chromium verifies TLS against the NSS database under its HOME, not the
# system bundle, so the same roots go there too. PEM-then-DER because the
# directory carries both encodings.
RUN mkdir -p "${HOME}/.pki/nssdb" \
    && certutil -N -d "sql:${HOME}/.pki/nssdb" --empty-password \
    && for f in /usr/local/share/ca-certificates/*; do \
        openssl x509 -in "$f" -out /tmp/ca.pem 2>/dev/null \
            || openssl x509 -inform DER -in "$f" -out /tmp/ca.pem; \
        certutil -A -d "sql:${HOME}/.pki/nssdb" \
            -n "host-$(basename "$f")" -t "C,," -i /tmp/ca.pem; \
    done \
    && chown -R kumoss:kumoss /home/kumoss/.pki

COPY --chown=kumoss:kumoss core/src ./src
COPY --chown=kumoss:kumoss core/prompts ./prompts

USER ${KUMOSS_UID}:${KUMOSS_GID}

EXPOSE 8000

CMD ["fastapi", "run", "src/main.py"]
