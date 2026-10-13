#!/bin/sh
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# Kumoss SearXNG entrypoint.
#
# The upstream image does not substitute environment variables in
# settings.yml, so resolve the ${SEARXNG_SECRET} placeholder here and
# point SearXNG at the rewritten copy before exec'ing the stock
# entrypoint. Falls back to a static example key when SEARXNG_SECRET is
# unset (local/dev only — set a real key via services/searxng/.env).
set -eu

: "${SEARXNG_SECRET:=c8f9e6b2a4d7f3e1b5c9d8a6f2e4b7c1d9e3f8a5b2c7d4e6f1a8b3c5d2e9f4a1}"

mkdir -p /tmp/searxng-config
sed "s|\${SEARXNG_SECRET}|${SEARXNG_SECRET}|g" \
    /etc/searxng/settings.yml > /tmp/searxng-config/settings.yml
export SEARXNG_SETTINGS_PATH=/tmp/searxng-config/settings.yml

exec /usr/local/searxng/entrypoint.sh
