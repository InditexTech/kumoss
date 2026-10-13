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

exec /usr/local/searxng/entrypoint.sh
