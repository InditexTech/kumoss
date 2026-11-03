#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 INDUSTRIA DE DISEÑO TEXTIL S.A. (INDITEX S.A.)
#
# SPDX-License-Identifier: Apache-2.0

# Brings Kumoss up on a local kind cluster with the Helm chart: the steps
# of the "Try it on kind" guide in one idempotent command. Re-run it to
# upgrade; anything after the options goes to `helm upgrade --install`.
#
#   charts/kind-up.sh                                  # chart from this checkout
#   ENV_FILE=core/.env CA_DIR=/usr/local/share/ca-certificates charts/kind-up.sh
#   CHART=oci://ghcr.io/inditextech/charts/kumoss CHART_VERSION=1.0.5 charts/kind-up.sh
#   charts/kind-up.sh --set notifications.enabled=true ...
#
# Settings (environment variables):
#   CLUSTER        kind cluster name                     (kumoss)
#   NAMESPACE      namespace and Helm release name       (kumoss)
#   CHART          chart path or OCI reference           (the chart next to this script)
#   CHART_VERSION  chart version, for an OCI CHART       (latest)
#   ENV_FILE       dotenv with the LLM / Git credentials, loaded into the
#                  Secret <release>-credentials (core.existingSecret).
#                  Quotes around values are stripped; keys the chart
#                  generates itself (tokens, database / Redis URLs, object
#                  storage keys) are skipped.                  (none)
#   CA_DIR         directory of PEM roots to trust behind a TLS-inspecting
#                  proxy, loaded into a ConfigMap for caBundle.  (none)
#   LOAD_IMAGES    1: pull the images on the host and load them into the
#                  node (the node cannot pull through a TLS-inspecting
#                  proxy); 0: let the node pull. (1 when CA_DIR is set)
#   HTTP_PORT      host port of the UI                   (80)
#   STORAGE_PORT   host port of artifact downloads       (9000)
#
# The host ports are fixed when the cluster is created; to change them,
# delete it first (kind delete cluster --name kumoss).
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER="${CLUSTER:-kumoss}"
NAMESPACE="${NAMESPACE:-kumoss}"
CHART="${CHART:-${script_dir}/kumoss}"
CHART_VERSION="${CHART_VERSION:-}"
ENV_FILE="${ENV_FILE:-}"
CA_DIR="${CA_DIR:-}"
LOAD_IMAGES="${LOAD_IMAGES:-$([ -n "${CA_DIR}" ] && echo 1 || echo 0)}"
HTTP_PORT="${HTTP_PORT:-80}"
STORAGE_PORT="${STORAGE_PORT:-9000}"
release="${NAMESPACE}"

log() { printf '\033[1m==> %s\033[0m\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

for tool in docker kind kubectl helm; do
    command -v "${tool}" >/dev/null || die "${tool} not found in PATH"
done
[ -z "${ENV_FILE}" ] || [ -f "${ENV_FILE}" ] || die "ENV_FILE ${ENV_FILE} not found"
[ -z "${CA_DIR}" ] || [ -d "${CA_DIR}" ] || die "CA_DIR ${CA_DIR} is not a directory"

tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT

# Apply a manifest generated with --dry-run, so re-runs update in place.
apply() { kubectl apply -f - >/dev/null; }

# --- Helm arguments ----------------------------------------------------

port_suffix() { [ "$1" = "$2" ] && echo "" || echo ":$1"; }
helm_args=(
    --namespace "${NAMESPACE}"
    --set proxy.service.type=NodePort
    --set proxy.service.nodePorts.http=30080
    --set proxy.service.nodePorts.storage=30900
    --set "publicUrl=http://localhost$(port_suffix "${HTTP_PORT}" 80)"
    --set "storagePublicUrl=http://localhost:${STORAGE_PORT}"
)
[ -z "${CHART_VERSION}" ] || helm_args+=(--version "${CHART_VERSION}")

[ -z "${ENV_FILE}" ] || helm_args+=(--set "core.existingSecret=${release}-credentials")
[ -z "${CA_DIR}" ] || helm_args+=(--set "caBundle.existingConfigMap=${release}-host-ca")
helm_args+=("$@")

# Render before touching any cluster, so a chart error (a missing
# required value...) stops the run with Helm's message.
helm template "${release}" "${CHART}" "${helm_args[@]}" > "${tmp}/rendered.yaml" \
    || die "helm template failed (see above)"

# --- Cluster -----------------------------------------------------------

if kind get clusters 2>/dev/null | grep -qx "${CLUSTER}"; then
    log "Using existing kind cluster ${CLUSTER}"
else
    log "Creating kind cluster ${CLUSTER} (UI on :${HTTP_PORT}, downloads on :${STORAGE_PORT})"
    kind create cluster --name "${CLUSTER}" --config - <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - { containerPort: 30080, hostPort: ${HTTP_PORT} }
      - { containerPort: 30900, hostPort: ${STORAGE_PORT} }
EOF
fi
kubectl config use-context "kind-${CLUSTER}" >/dev/null

kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | apply

# --- Credentials -------------------------------------------------------

if [ -n "${ENV_FILE}" ]; then
    log "Loading credentials from ${ENV_FILE} into Secret ${release}-credentials"
    # kubectl --from-env-file keeps surrounding quotes, which Compose's
    # dotenv strips: normalise to bare KEY=value lines first. The file is
    # parsed, never sourced.
    clean="${tmp}/credentials.env"
    (umask 077 && : > "${clean}")
    while IFS= read -r line || [ -n "${line}" ]; do
        line="${line%$'\r'}"
        [[ "${line}" =~ ^[[:space:]]*(#|$) ]] && continue
        [[ "${line}" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
        key="${BASH_REMATCH[2]}"
        value="${BASH_REMATCH[3]}"
        case "${key}" in
            KUMOSS_IAC_TOKEN | KUMOSS_NOTIFICATIONS_TOKEN | KUMOSS_SQL_DATABASE_URL | \
                PHOENIX_SQL_DATABASE_URL | KUMOSS_REDIS_URL | RUSTFS_ACCESS_KEY | RUSTFS_SECRET_KEY)
                continue ;;
        esac
        # Compose dotenv: a quoted value may be followed by a comment; an
        # unquoted one ends at " #". A '#' inside quotes or not preceded
        # by whitespace is part of the value.
        if [[ "${value}" =~ ^\'([^\']*)\'[[:space:]]*(#.*)?$ \
            || "${value}" =~ ^\"([^\"]*)\"[[:space:]]*(#.*)?$ \
            || "${value}" =~ ^\"(.*)\"[[:space:]]*$ ]]; then
            value="${BASH_REMATCH[1]}"
        else
            value="${value%%[[:space:]]#*}"
            value="${value%"${value##*[![:space:]]}"}"
        fi
        printf '%s=%s\n' "${key}" "${value}" >> "${clean}"
    done < "${ENV_FILE}"
    kubectl -n "${NAMESPACE}" create secret generic "${release}-credentials" \
        --from-env-file="${clean}" --dry-run=client -o yaml | apply
fi

# --- Corporate CA roots ------------------------------------------------

if [ -n "${CA_DIR}" ]; then
    log "Loading CA roots from ${CA_DIR} into ConfigMap ${release}-host-ca"
    kubectl -n "${NAMESPACE}" create configmap "${release}-host-ca" \
        --from-file="${CA_DIR}" --dry-run=client -o yaml | apply
fi

# --- Images ------------------------------------------------------------

if [ "${LOAD_IMAGES}" = "1" ]; then
    node="${CLUSTER}-control-plane"
    platform="linux/$(docker version --format '{{.Server.Arch}}')"
    mapfile -t images < <(
        sed -n 's/^[[:space:]]*image:[[:space:]]*"\{0,1\}\([^"[:space:]]*\)"\{0,1\}.*/\1/p' "${tmp}/rendered.yaml" \
            | sort -u
    )
    [ "${#images[@]}" -gt 0 ] || die "helm template rendered no images"
    missing=()
    for image in "${images[@]}"; do
        ref="${image}"
        [[ "${ref%%/*}" == *.* ]] || ref="docker.io/${ref}"
        [[ "${ref}" == */*/* ]] || ref="${ref/docker.io\//docker.io/library/}"
        docker exec "${node}" crictl inspecti "${ref}" >/dev/null 2>&1 || missing+=("${image}")
    done
    if [ "${#missing[@]}" -eq 0 ]; then
        log "All ${#images[@]} images already on the node"
    else
        log "Pulling ${#missing[@]} image(s) on the host"
        for image in "${missing[@]}"; do
            echo "    ${image}"
            docker image inspect "${image}" >/dev/null 2>&1 || docker pull -q "${image}" >/dev/null
        done
        # One single-platform archive: kind load docker-image fails on
        # multi-platform images.
        log "Loading them into ${node}"
        docker save --platform "${platform}" -o "${tmp}/images.tar" "${missing[@]}"
        kind load image-archive "${tmp}/images.tar" --name "${CLUSTER}"
    fi
fi

# --- Install -----------------------------------------------------------

log "Installing release ${release}"
helm upgrade --install "${release}" "${CHART}" "${helm_args[@]}" --wait --timeout 10m
helm test "${release}" --namespace "${NAMESPACE}"

log "Kumoss is up at http://localhost$(port_suffix "${HTTP_PORT}" 80) (Phoenix under /monitoring/)"
