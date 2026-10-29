FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

FROM python:3.14-bookworm@sha256:7ee7e4d4fb42c3ad45b8fdc473b64ec69c3cf6e80ae5d52f6fa55f77fac29027

# Minimal apt deps the core actually uses at runtime: git for cloning user
# repos, ripgrep for the workspace inspection tools, curl for general use.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Extra CA roots from the "host-certs" build context (docker/certs, empty
# by default; the override points it at the host's corporate roots behind a
# TLS-inspecting proxy). Build-time HTTPS — the Python index — needs them
# to anchor the proxy's re-signed chain.
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

COPY --chown=kumoss:kumoss core/src ./src
COPY --chown=kumoss:kumoss core/prompts ./prompts
COPY core/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER ${KUMOSS_UID}:${KUMOSS_GID}

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["fastapi", "run", "src/main.py"]
