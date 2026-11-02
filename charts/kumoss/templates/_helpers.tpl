{{/* Chart name, truncated to the DNS label limit. */}}
{{- define "kumoss.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Release-scoped base name; component names append "-<component>". */}}
{{- define "kumoss.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else if contains (include "kumoss.name" .) .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name (include "kumoss.name" .) | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}

{{/*
Name of a component's resources. The base is truncated, never the
suffix, so long release names cannot collapse two components (e.g.
"core" and "core-db") onto one name.
Usage: include "kumoss.component" (list . "core")
*/}}
{{- define "kumoss.component" -}}
{{- $suffix := index . 1 }}
{{- $base := include "kumoss.fullname" (index . 0) | trunc (int (sub 62 (len $suffix))) | trimSuffix "-" }}
{{- printf "%s-%s" $base $suffix }}
{{- end }}

{{- define "kumoss.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ include "kumoss.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/* Usage: include "kumoss.selectorLabels" (list . "core") */}}
{{- define "kumoss.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kumoss.name" (index . 0) }}
app.kubernetes.io/instance: {{ (index . 0).Release.Name }}
app.kubernetes.io/component: {{ index . 1 }}
{{- end }}

{{/* Usage: include "kumoss.componentLabels" (list . "core") */}}
{{- define "kumoss.componentLabels" -}}
{{ include "kumoss.labels" (index . 0) }}
app.kubernetes.io/component: {{ index . 1 }}
{{- end }}

{{/* Image reference; Kumoss images default their tag to the appVersion. Usage: include "kumoss.image" (list . .Values.core.image) */}}
{{- define "kumoss.image" -}}
{{- $image := index . 1 }}
{{- printf "%s:%s" $image.repository (default (index . 0).Chart.AppVersion $image.tag) }}
{{- end }}

{{/* Generated-credentials Secret (tokens, passwords, connection URLs). */}}
{{- define "kumoss.internalSecret" -}}
{{- default (include "kumoss.component" (list . "internal")) .Values.secrets.existingSecret }}
{{- end }}

{{/* Secret holding a component's secretEnv. Usage: include "kumoss.envSecret" (list . "core") */}}
{{- define "kumoss.envSecret" -}}
{{- include "kumoss.component" (list (index . 0) (printf "%s-env" (index . 1))) }}
{{- end }}

{{/* Env sources shared by every component. Usage: include "kumoss.envFrom" (list . "core" .Values.core) */}}
{{- define "kumoss.envFrom" -}}
{{- $root := index . 0 }}
{{- $name := index . 1 }}
{{- $c := index . 2 }}
{{- if or $c.secretEnv $c.existingSecret }}
envFrom:
  {{- if $c.secretEnv }}
  - secretRef:
      name: {{ include "kumoss.envSecret" (list $root $name) }}
  {{- end }}
  {{- if $c.existingSecret }}
  - secretRef:
      name: {{ $c.existingSecret }}
  {{- end }}
{{- end }}
{{- end }}

{{/* Plain env map + extraEnv list, as env entries (no "env:" key). */}}
{{- define "kumoss.extraEnv" -}}
{{- range $k, $v := .env }}
- name: {{ $k }}
  value: {{ $v | toString | quote }}
{{- end }}
{{- with .extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end }}

{{/* Env entry read from the internal Secret. Usage: include "kumoss.secretKeyRef" (list . "ENV_NAME" "secretKey") */}}
{{- define "kumoss.secretKeyRef" -}}
- name: {{ index . 1 }}
  valueFrom:
    secretKeyRef:
      name: {{ include "kumoss.internalSecret" (index . 0) }}
      key: {{ index . 2 }}
{{- end }}

{{/* Scheduling block shared by every pod. */}}
{{- define "kumoss.scheduling" -}}
{{- with .nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end }}

{{/* Workspaces claim name. */}}
{{- define "kumoss.workspacesClaim" -}}
{{- default (include "kumoss.component" (list . "workspaces")) .Values.workspaces.existingClaim }}
{{- end }}

{{/*
In-cluster service URLs. The repository's config.yaml and nginx.conf
use the docker-compose hostnames; the chart rewrites them to these.
*/}}
{{- define "kumoss.coreHost" -}}{{ include "kumoss.component" (list . "core") }}{{- end }}
{{- define "kumoss.phoenixHost" -}}{{ include "kumoss.component" (list . "phoenix") }}{{- end }}
{{- define "kumoss.objectStorageHost" -}}{{ include "kumoss.component" (list . "object-storage") }}{{- end }}

{{/*
The core's config.yaml: the repository file, then the chart's in-cluster
wiring, then the user's `config` overrides (each layer wins).
*/}}
{{- define "kumoss.coreConfig" -}}
{{- $base := .Files.Get "files/config.yaml" | fromYaml }}
{{- $wiring := dict
  "http" (dict "cors_origins" (list .Values.publicUrl))
  "services" (dict
    "iac" (dict "endpoint" (printf "http://%s:8082" (include "kumoss.component" (list . "iac"))))
    "notifications" (dict
      "enabled" .Values.notifications.enabled
      "endpoint" (ternary (printf "http://%s:8080" (include "kumoss.component" (list . "notifications"))) "" .Values.notifications.enabled)))
}}
{{- if .Values.phoenix.enabled }}
{{- $_ := set $wiring "telemetry" (dict "collector_url" (printf "http://%s:6006/" (include "kumoss.phoenixHost" .))) }}
{{- end }}
{{- if .Values.searxng.enabled }}
{{- $_ := set $wiring "web_search" (dict "provider" "searxng" "endpoint" (printf "http://%s:8888" (include "kumoss.component" (list . "searxng")))) }}
{{- else }}
{{- /* Both fields: SearchConfig rejects an endpoint without a provider. */}}
{{- $_ := set $wiring "web_search" (dict "provider" "" "endpoint" "") }}
{{- end }}
{{- if .Values.objectStorage.enabled }}
{{- $_ := set $wiring "storage" (dict
  "provider" "RUSTFS"
  "endpoint_url" (printf "http://%s:9000" (include "kumoss.objectStorageHost" .))
  "public_endpoint_url" .Values.storagePublicUrl) }}
{{- end }}
{{- $cfg := mustMergeOverwrite $base $wiring (deepCopy .Values.config) }}
{{- toYaml $cfg }}
{{- end }}

{{/*
The proxy's nginx.conf: the repository file with the docker-compose
upstream hostnames swapped for this release's Services. A disabled
backend points at a closed local port, so nginx still starts (it refuses
to load a config with an unresolvable upstream) and that path answers 502.
*/}}
{{- define "kumoss.nginxConf" -}}
{{- $off := "http://127.0.0.1:9" }}
{{- $phoenix := ternary (printf "http://%s:6006" (include "kumoss.phoenixHost" .)) $off (and .Values.phoenix.enabled .Values.phoenix.exposeViaProxy) }}
{{- $storage := ternary (printf "http://%s:9000" (include "kumoss.objectStorageHost" .)) $off .Values.objectStorage.enabled }}
{{- .Files.Get "files/nginx.conf"
  | replace "http://core:8000" (printf "http://%s:8000" (include "kumoss.coreHost" .))
  | replace "http://phoenix:6006" $phoenix
  | replace "http://object-storage:9000" $storage }}
{{- end }}

{{/*
Init container that blocks until a bundled Postgres accepts connections:
the core and Phoenix exit on a refused connection at startup instead of
retrying. Usage: include "kumoss.waitForPostgres" (list . "core-db")
*/}}
{{- define "kumoss.waitForPostgres" -}}
{{- $root := index . 0 }}
{{- $host := include "kumoss.component" (list $root (index . 1)) }}
- name: wait-for-{{ index . 1 }}
  image: "{{ $root.Values.postgres.image.repository }}:{{ $root.Values.postgres.image.tag }}"
  imagePullPolicy: {{ $root.Values.postgres.image.pullPolicy }}
  command: ["sh", "-c", "until pg_isready -q -U postgres -h {{ $host }} -p 5432; do sleep 2; done"]
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    allowPrivilegeEscalation: false
    capabilities:
      drop: ["ALL"]
{{- end }}

{{/* A component's ServiceAccount name. Usage: include "kumoss.serviceAccountName" (list . "core") */}}
{{- define "kumoss.serviceAccountName" -}}
{{- $root := index . 0 }}
{{- $sa := (index $root.Values (index . 1)).serviceAccount }}
{{- if $sa.create }}
{{- default (include "kumoss.component" (list $root (index . 1))) $sa.name }}
{{- else }}
{{- default "default" $sa.name }}
{{- end }}
{{- end }}

{{/* Pod identity fields. Usage: include "kumoss.podIdentity" (list . "core") */}}
{{- define "kumoss.podIdentity" -}}
serviceAccountName: {{ include "kumoss.serviceAccountName" . }}
automountServiceAccountToken: {{ (index (index . 0).Values (index . 1)).serviceAccount.automount }}
{{- end }}

{{/*
Hash of the secret inputs a pod reads: the shared credentials and
external URLs (all stored in the internal Secret) plus the component's
own secretEnv. Changing a Secret does not restart its readers, so pods
carry this to roll when an upgrade changes them. Generated values are
not inputs: they never change on upgrade. Secrets referenced through
existingSecret are managed outside the chart; restart after rotating
them. Usage: include "kumoss.secretsChecksum" (list . "core")
*/}}
{{- define "kumoss.secretsChecksum" -}}
{{- $root := index . 0 }}
{{- $v := $root.Values }}
{{- toJson (dict
  "shared" $v.secrets
  "externalUrls" (list $v.postgres.core.externalUrl $v.postgres.phoenix.externalUrl $v.redis.externalUrl)
  "secretEnv" ((index $v (index . 1)).secretEnv | default dict)) | sha256sum }}
{{- end }}
