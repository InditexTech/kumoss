#!/bin/sh
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# Kumoss core entrypoint.
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

# Split one file into a PEM file per certificate under $2. A file may be
# a single PEM or DER certificate or a bundle of several PEM blocks
# (`openssl x509` alone would keep only the first). Anything that is not
# a certificate (the context's .gitkeep) yields nothing.
split_certs() {
    name="$(basename "$1")"
    if grep -q -- "-----BEGIN CERTIFICATE-----" "$1"; then
        # Files concatenated without a trailing newline glue an END and
        # the next BEGIN onto one line: break after every END first.
        awk -v prefix="$2/${name}" '
            function emit(l) {
                if (l ~ /-----BEGIN CERTIFICATE-----/) { n++; out = prefix "." n ".pem" }
                if (out != "") print l > out
                if (l ~ /-----END CERTIFICATE-----/) { close(out); out = "" }
            }
            {
                gsub(/-----END CERTIFICATE-----/, "&\n")
                k = split($0, parts, "\n")
                for (i = 1; i <= k; i++) if (parts[i] != "") emit(parts[i])
            }
        ' "$1"
    elif openssl x509 -inform DER -in "$1" -out "$2/${name}.pem" 2>/dev/null; then
        :
    else
        rm -f "$2/${name}.pem"
    fi
}

if [ -d "${CA_DIR}" ] && [ -n "$(ls -A "${CA_DIR}" 2>/dev/null)" ]; then
    echo "Trusting extra CA roots from ${CA_DIR}"

    certs="${HOME}/.kumoss-ca"
    rm -rf "${certs}"
    mkdir -p "${certs}"
    for f in "${CA_DIR}"/*; do
        [ -f "$f" ] && split_certs "$f" "${certs}"
    done

    # Combined bundle: the image's public roots plus the corporate ones.
    bundle="${HOME}/ca-certificates.crt"
    cat /etc/ssl/certs/ca-certificates.crt > "${bundle}"
    for c in "${certs}"/*.pem; do
        [ -f "$c" ] || continue
        cat "$c" >> "${bundle}"
        echo >> "${bundle}"
    done
    export SSL_CERT_FILE="${bundle}"
    export REQUESTS_CA_BUNDLE="${bundle}"
    export NODE_EXTRA_CA_CERTS="${bundle}"
    export AWS_CA_BUNDLE="${bundle}"

    # Chromium verifies TLS against its own NSS database, not the system
    # bundle. Import the same roots there, one nickname per certificate.
    nssdb="sql:${HOME}/.pki/nssdb"
    mkdir -p "${HOME}/.pki/nssdb"
    for c in "${certs}"/*.pem; do
        [ -f "$c" ] || continue
        certutil -A -d "${nssdb}" \
            -n "host-$(basename "$c" .pem)" -t "C,," -i "$c"
    done
fi

exec "$@"
