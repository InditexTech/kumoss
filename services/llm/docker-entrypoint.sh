#!/bin/sh
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# Kumoss LLM sidecar entrypoint (CA handling ported from core/docker-entrypoint.sh).
#
# The image ships with the public CA roots only. Behind a TLS-inspecting
# proxy, docker-compose.override.yml mounts the host's corporate roots at
# KUMOSS_CA_DIR; when that directory has certificates, merge them into a
# bundle under HOME and point the Python and Node clients at it, then
# import them into Chromium's NSS database (the `web_search` page reads).
# The container runs unprivileged, so the system store is left untouched.
# On a normal network the directory is empty and this is a no-op.
set -eu

CA_DIR="${KUMOSS_CA_DIR:-/usr/local/share/ca-certificates/host}"

# Normalise one certificate (PEM or DER) to PEM on stdout; exit non-zero
# for anything that is not a certificate (the context's .gitkeep).
to_pem() {
    openssl x509 -in "$1" -out - 2>/dev/null \
        || openssl x509 -inform DER -in "$1" -out - 2>/dev/null
}

if [ -d "${CA_DIR}" ] && [ -n "$(ls -A "${CA_DIR}" 2>/dev/null)" ]; then
    echo "Trusting extra CA roots from ${CA_DIR}"

    # Combined bundle: the image's public roots plus the corporate ones.
    bundle="${HOME}/ca-certificates.crt"
    cat /etc/ssl/certs/ca-certificates.crt > "${bundle}"
    for f in "${CA_DIR}"/*; do
        to_pem "$f" >> "${bundle}" || continue
    done
    export SSL_CERT_FILE="${bundle}"
    export REQUESTS_CA_BUNDLE="${bundle}"
    export NODE_EXTRA_CA_CERTS="${bundle}"

    # Chromium verifies TLS against its own NSS database, not the system
    # bundle. Import the same roots there.
    nssdb="sql:${HOME}/.pki/nssdb"
    mkdir -p "${HOME}/.pki/nssdb"
    for f in "${CA_DIR}"/*; do
        to_pem "$f" > "${HOME}/ca.pem" || continue
        certutil -A -d "${nssdb}" \
            -n "host-$(basename "$f")" -t "C,," -i "${HOME}/ca.pem"
    done
fi

exec "$@"
