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
ARG NEBULA_UID=10001
ARG NEBULA_GID=10001
RUN groupadd --gid "${NEBULA_GID}" nebula \
    && useradd --uid "${NEBULA_UID}" --gid "${NEBULA_GID}" \
        --create-home --home-dir /home/nebula --shell /usr/sbin/nologin nebula \
    && mkdir -p /workspaces && chown nebula:nebula /workspaces

# config.yaml
COPY config.yaml /etc/nebula/

WORKDIR /usr/src/app

# Python dependencies
RUN pip install --no-cache-dir uv
COPY core/pyproject.toml .
RUN uv pip install --system --prerelease=allow -r pyproject.toml

COPY --chown=nebula:nebula core/ .

ENV HOME=/home/nebula

USER ${NEBULA_UID}:${NEBULA_GID}

EXPOSE 8000

CMD ["fastapi", "run", "src/main.py"]
