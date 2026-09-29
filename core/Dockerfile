FROM python:3.13-bookworm

# Minimal apt deps the core actually uses at runtime: git for cloning user
# repos, ripgrep for the workspace inspection tools, curl for general use.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ripgrep \
    && rm -rf /var/lib/apt/lists/*

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

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /usr/src/app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CONCURRENT_DOWNLOADS=4 \
    PATH="/usr/src/app/.venv/bin:$PATH" \
    HOME=/home/kumoss

COPY core/pyproject.toml core/uv.lock ./

RUN uv sync --frozen --no-install-project --no-default-groups

COPY --chown=kumoss:kumoss core/src ./src
COPY --chown=kumoss:kumoss core/prompts ./prompts

USER ${KUMOSS_UID}:${KUMOSS_GID}

EXPOSE 8000

CMD ["fastapi", "run", "src/main.py"]
