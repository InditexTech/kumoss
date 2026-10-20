#!/bin/sh
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# Kumoss SearXNG entrypoint.
#
# The upstream image does not substitute environment variables in
# settings.yml, so resolve the ${SEARXNG_SECRET} placeholder here and
# point SearXNG at the rewritten copy before exec'ing the stock
# entrypoint. When SEARXNG_SECRET is unset a random key is generated —
# good enough for a throwaway local stack, but it rotates on every
# container start; set a real key via services/searxng/.env.
set -eu

if [ -z "${SEARXNG_SECRET:-}" ]; then
    SEARXNG_SECRET="$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9')"
    export SEARXNG_SECRET
fi

mkdir -p /tmp/searxng-config
sed "s|\${SEARXNG_SECRET}|${SEARXNG_SECRET}|g" \
    /etc/searxng/settings.yml > /tmp/searxng-config/settings.yml
export SEARXNG_SETTINGS_PATH=/tmp/searxng-config/settings.yml

# Behind a TLS-inspecting proxy the override mounts the host's corporate
# roots at KUMOSS_CA_DIR; merge them into a bundle under /tmp and point
# the Python client at it so outbound engine calls anchor the re-signed
# chain. The container runs unprivileged, so the system store is left
# untouched. A no-op on a normal network (empty directory).
CA_DIR="${KUMOSS_CA_DIR:-/usr/local/share/ca-certificates/host}"
if [ -d "${CA_DIR}" ] && [ -n "$(ls -A "${CA_DIR}" 2>/dev/null)" ]; then
    echo "Trusting extra CA roots from ${CA_DIR}"
    bundle=/tmp/ca-certificates.crt
    cat /etc/ssl/certs/ca-certificates.crt > "${bundle}"
    for f in "${CA_DIR}"/*; do
        { openssl x509 -in "$f" -out - 2>/dev/null \
            || openssl x509 -inform DER -in "$f" -out - 2>/dev/null; } \
            >> "${bundle}" || continue
    done
    export SSL_CERT_FILE="${bundle}"
    export REQUESTS_CA_BUNDLE="${bundle}"
fi

exec /usr/local/searxng/entrypoint.sh
