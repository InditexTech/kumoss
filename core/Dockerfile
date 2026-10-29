FROM rust:1-bookworm@sha256:9181b56c2a21ab1d5e73cffe04fc762426d30aa7fac3c91141dd033f49a7fc8b AS build

# Extra CA roots from the "host-certs" build context (docker/certs, empty
# by default; the override points it at the host's corporate roots behind a
# TLS-inspecting proxy). Build-time HTTPS — the crates.io index — needs them
# to anchor the proxy's re-signed chain.
COPY --from=host-certs / /usr/local/share/ca-certificates/
RUN update-ca-certificates

# crates.io downloads of the larger SDK crates are retried on flaky links.
ENV CARGO_NET_RETRY=10

WORKDIR /build

# Dependencies first, against a placeholder crate, so source edits do not
# rebuild them.
COPY core/Cargo.toml core/Cargo.lock ./
RUN mkdir src \
    && echo 'fn main() {}' > src/main.rs \
    && touch src/lib.rs \
    && cargo build --release --locked \
    && rm -rf src

COPY core/src ./src
COPY core/resources ./resources
RUN touch src/main.rs src/lib.rs \
    && cargo build --release --locked

FROM debian:bookworm-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3

# Minimal apt deps the core actually uses at runtime: git for cloning user
# repos, ripgrep for the workspace inspection tools, curl for general use,
# openssl for the entrypoint's CA bundle merge, ca-certificates for TLS.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ripgrep curl openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

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

ENV HOME=/home/kumoss

WORKDIR /usr/src/app

COPY --from=build /build/target/release/kumoss-core /usr/src/app/kumoss-core
COPY --chown=kumoss:kumoss core/prompts ./prompts
COPY core/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER ${KUMOSS_UID}:${KUMOSS_GID}

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/usr/src/app/kumoss-core"]
