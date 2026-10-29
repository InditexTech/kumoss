# Pin the datetagged build that this service was validated against.
# SearXNG is a rolling release (every master commit is a release), so
# `:latest` would silently drift at each rebuild; bumps are deliberate:
# `docker pull searxng/searxng:latest`, note its version printed at
# container start, update the tag, rebuild and rerun the verification.
FROM searxng/searxng:2026.10.13-22c64b8d3

# Switch to root to set permissions
USER root

# Copy custom settings
COPY settings.yml /etc/searxng/settings.yml

# Extra CA roots from the "host-certs" build context (docker/certs, empty by
# default; the override points it at the host's corporate roots behind a
# TLS-inspecting proxy), so outbound HTTPS anchors the proxy's re-signed
# chain. update-ca-certificates is a no-op when the directory is empty.
COPY --from=host-certs / /usr/local/share/ca-certificates/
RUN update-ca-certificates

# Fix ownership and permissions
RUN chown -R searxng:searxng /etc/searxng

# Switch back to searxng user
USER searxng

# Use a non-default port so the container does not collide with other
# services in the same Docker network (e.g. Kumoss's notifications:8080,
# mapping:8081, iac:8082, authz:8083)
ENV SEARXNG_PORT=8888

# Expose port
EXPOSE 8888

# Kumoss entrypoint: resolves SEARXNG_SECRET into the mounted
# settings.yml before exec'ing the stock image entrypoint
COPY --chown=searxng:searxng docker-entrypoint.sh /usr/local/searxng/docker-entrypoint.sh
RUN chmod +x /usr/local/searxng/docker-entrypoint.sh
ENTRYPOINT ["/usr/local/searxng/docker-entrypoint.sh"]
