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
#
# A caller-provided SEARXNG_SETTINGS_PATH wins: rewrite that file instead
# of the built-in one, so a chart/compose override that points at its own
# settings is honoured rather than silently replaced.
set -eu

if [ -z "${SEARXNG_SECRET:-}" ]; then
    SEARXNG_SECRET="$(head -c 24 /dev/urandom | base64 | tr -dc 'a-zA-Z0-9')"
    export SEARXNG_SECRET
fi

# settings.yml is YAML, and secret_key sits in a double-quoted scalar: a
# `"` or `\` in the secret must be escaped or the file stops parsing.
yaml_escape() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

# Substitute with index/substr rather than a regex replacement: in both
# sed's s/// and awk's gsub() a `&` in the replacement means "the matched
# text", and `|` breaks sed's delimiter, so either would corrupt or reject
# a valid secret. This splices the literal value in verbatim.
substitute_secret() {
    secret="$(yaml_escape "$1")" awk '
        BEGIN {
            secret = ENVIRON["secret"]
            needle = "${SEARXNG_SECRET}"
        }
        {
            out = ""
            while ((i = index($0, needle)) > 0) {
                out = out substr($0, 1, i - 1) secret
                $0 = substr($0, i + length(needle))
            }
            print out $0
        }
    ' "$2"
}

src="${SEARXNG_SETTINGS_PATH:-/etc/searxng/settings.yml}"
mkdir -p /tmp/searxng-config
substitute_secret "${SEARXNG_SECRET}" "${src}" > /tmp/searxng-config/settings.yml
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
    # A PEM file may hold several certificates (a bundle), so append it
    # whole rather than through `openssl x509`, which keeps only the
    # first; DER files hold one and are converted. Breaking the line
    # after every END keeps certificates glued by a missing newline.
    for f in "${CA_DIR}"/*; do
        [ -f "$f" ] || continue
        if grep -q -- "-----BEGIN CERTIFICATE-----" "$f"; then
            sed 's/-----END CERTIFICATE-----/&\n/g' "$f" >> "${bundle}"
        else
            openssl x509 -inform DER -in "$f" -out - 2>/dev/null >> "${bundle}" || continue
        fi
    done
    export SSL_CERT_FILE="${bundle}"
    export REQUESTS_CA_BUNDLE="${bundle}"
fi

exec /usr/local/searxng/entrypoint.sh
