FROM ghcr.io/astral-sh/uv:0.12.22@sha256:f513a91fc62fe7c17567eee97230dd198e43edb8a9fbecca843714a4358fe1bc AS uv

FROM python:3.13-bookworm@sha256:ab62bdaec8f090e565b8c76a8cac990229c28a42725f356cc32d9f4dea29806d

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
ARG NEBULA_UID=10001
ARG NEBULA_GID=10001
RUN groupadd --gid "${NEBULA_GID}" nebula \
    && useradd --uid "${NEBULA_UID}" --gid "${NEBULA_GID}" \
        --create-home --home-dir /home/nebula --shell /usr/sbin/nologin nebula \
    && mkdir -p /workspaces && chown nebula:nebula /workspaces

# config.yaml
COPY config.yaml /etc/nebula/

COPY --from=uv /uv /uvx /bin/

WORKDIR /usr/src/app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CONCURRENT_DOWNLOADS=4 \
    PATH="/usr/src/app/.venv/bin:$PATH" \
    HOME=/home/nebula

COPY core/pyproject.toml core/uv.lock ./

RUN uv sync --locked --no-install-project --no-default-groups

COPY --chown=nebula:nebula core/src ./src
COPY --chown=nebula:nebula core/prompts ./prompts

USER ${NEBULA_UID}:${NEBULA_GID}

EXPOSE 8000

CMD ["fastapi", "run", "src/main.py"]
