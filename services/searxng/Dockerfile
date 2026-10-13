FROM searxng/searxng:latest

# Switch to root to set permissions
USER root

# Copy custom settings
COPY settings.yml /etc/searxng/settings.yml

# Pull corporate CA certificates in via an additional build context
# (see docker-compose.yml: build.additional_contexts) so the repo holds
# no local copies of them.
COPY --from=host-certs / /usr/local/share/ca-certificates/

# Trust them so outbound HTTPS works behind the MITM proxy
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
