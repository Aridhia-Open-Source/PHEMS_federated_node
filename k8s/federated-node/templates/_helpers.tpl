{{/*
Expand the name of the chart.
*/}}
{{- define "federated-node.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "federated-node.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "federated-node.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

# To support the task controller subchart we will need to include
# a custom path as helpers are merged and the individual chart values
# are then applied
{{- define "backend-image" -}}
{{ printf "%s:%s" (.Values.backend.image) ((.Values.backend.tag) | default (include "image-tag" . | trim)) }}
{{- end }}
{{- define "fn-alpine" -}}
{{ printf "%s:%s" (.Values.alpine.image) ((.Values.alpine.tag) | default (include "image-tag" . | trim)) }}
{{- end }}
{{- define "image-tag" -}}
{{ (.Values.default_image_tag) | default .Chart.AppVersion }}
{{- end }}
{{/* The Dagster code image. Run pods inherit it via DAGSTER_CURRENT_IMAGE. */}}
{{- define "dagster-fn-image" -}}
{{ printf "%s:%s" (.Values.fnDagster.image) ((.Values.fnDagster.tag) | default (include "image-tag" . | trim)) }}
{{- end }}
{{- define "dagsterCodeServerName" -}}
{{- ((.Values.fnDagster).codeServer).name | default "dagster-fn" -}}
{{- end }}
{{- define "dagsterCodeServerPort" -}}
{{- ((.Values.fnDagster).codeServer).port | default 3030 -}}
{{- end }}
{{- define "dagsterCodeServerServiceAccount" -}}
{{- printf "%s-dagster-code-server" .Release.Name -}}
{{- end }}
{{/* Not release-prefixed: the subchart names it in a value, which cannot be
     templated. One release per namespace, as with dagster-env-config. */}}
{{- define "dagsterWorkspaceConfigMap" -}}
dagster-workspace
{{- end }}
{{- define "keycloak-image-tag" -}}
{{ (.Values.keycloak).tag | default .Chart.AppVersion }}
{{- end }}
{{- define "keycloak-image" -}}
{{ printf "%s:%s" ((.Values.keycloak).image | default "ghcr.io/aridhia-open-source/federated_keycloak") (include "keycloak-image-tag" . | trim) }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "federated-node.labels" -}}
helm.sh/chart: {{ include "federated-node.chart" . }}
{{ include "federated-node.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "federated-node.selectorLabels" -}}
app.kubernetes.io/name: {{ include "federated-node.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "backendDbName" -}}
  {{ .Values.backend.db.name | quote }}
{{- end -}}

{{- define "backendDbUser" -}}
  {{ .Values.backend.db.user | quote }}
{{- end -}}

{{- define "dbKeycloakName" -}}
  {{ .Values.keycloak.db.name | quote }}
{{- end -}}

{{- define "dbKeycloakHost" }}
  {{- if eq .Values.db.host "db" }}
    {{- print "db." .Release.Namespace ".svc.cluster.local" | quote }}
  {{- else }}
    {{- .Values.db.host }}
  {{- end }}
{{- end }}

{{- define "tokenLife" -}}
  {{ int .Values.token.life  | default 2592000 | quote }}
{{- end -}}

{{- define "randomPass" -}}
{{ randAlphaNum 24 | b64enc | quote }}
{{- end -}}

{{- define "randomSecret" -}}
{{ randAlphaNum 24 | b64enc | quote }}
{{- end -}}

{{- define "rollMe" -}}
{{ randAlphaNum 5 | quote }}
{{- end -}}

{{- define "nonRootSC" -}}
securityContext:
  allowPrivilegeEscalation: false
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
  capabilities:
    drop: [ "ALL" ]
{{- end -}}

# Init container that blocks until the target postgres accepts connections.
# Expects a dict: { ctx: $, host: <string>, port: <string|int> }
{{- define "pgWaitContainer" -}}
{{- $ctx := .ctx -}}
- name: wait-for-db
  image: {{ include "fn-alpine" $ctx }}
  imagePullPolicy: {{ $ctx.Values.pullPolicy }}
  {{- include "nonRootSC" $ctx | nindent 2 }}
  command:
    - sh
    - -c
    - |
      until pg_isready -h $PGHOST -p $PGPORT; do
        echo "waiting for postgres..."
        sleep 2
      done
  env:
    - name: PGHOST
      value: {{ .host | quote }}
    - name: PGPORT
      value: {{ .port | quote }}
{{- end -}}

# In case of updating existing entities in hooks, use these default labels/annotations
# so helm knows they are part of this chart on future updates
{{- define "defaultLabels" -}}
    app.kubernetes.io/managed-by: Helm
{{- end -}}
{{- define "defaultAnnotations" -}}
    meta.helm.sh/release-name: {{ .Release.Name }}
    meta.helm.sh/release-namespace: {{ .Release.Namespace }}
{{- end -}}
{{- define "cspDomains" -}}
  {{- join ", " (.Values.integrations).domains -}}
{{- end -}}
{{- define "cspDomainsSpace" -}}
  {{- join " " (.Values.integrations).domains -}}
{{- end -}}
{{- define "kc_namespace" -}}
{{ ((.Values.global).namespaces).keycloak | default "keycloak" }}
{{- end -}}
{{- define "tasks_namespace" -}}
{{ ((.Values.global).namespaces).tasks | default "tasks" }}
{{- end -}}
{{- define "controller_namespace" -}}
{{ ((.Values.global).namespaces).controller | default "fn-controller" }}
{{- end -}}
{{- define "testsBaseUrl" }}
{{- if not .Values.local_development -}}
https://{{ .Values.host }}
{{- else -}}
http://backend.{{ .Release.Namespace }}.svc:{{ .Values.federatedNode.port }}
{{- end -}}
{{- end }}

{{/*
The in-cluster URL Dagster uses to reach the FN backend API. Defaults to the
release namespace so the chart is not pinned to a namespace called "fn";
set backend.uri explicitly to override (e.g. an external hostname).
*/}}
{{- define "backendUri" -}}
{{- if .Values.backend.uri -}}
{{ .Values.backend.uri }}
{{- else -}}
http://backend.{{ .Release.Namespace }}.svc:{{ .Values.federatedNode.port }}
{{- end -}}
{{- end }}

{{- define "backendResultsPVCName" -}}
{{ printf "backend-results-%s-pv-vc" (.Values.storage.capacity | default "10Gi") | lower }}
{{- end }}
{{- define "backendResultsPVName" -}}
{{- printf "%s-backend-results-%s-pv" .Release.Name (.Values.storage.capacity | default "10Gi") | lower }}
{{- end }}
{{- define "backendResultsStorageClassName" -}}
{{- printf "%s-shared-results" .Release.Name | lower }}
{{- end }}
{{- define "dagsterArtifactsPVCName" -}}
{{- .Values.fnDagster.artifactsPvcName | default "artifacts-pvc" }}
{{- end }}
{{- define "dagsterArtifactsPVName" -}}
{{- printf "%s-dagster-artifacts-%s-pv" .Release.Name (.Values.storage.capacity | default "10Gi") | lower }}
{{- end }}
{{- define "dagsterArtifactsStorageClassName" -}}
{{- printf "%s-dagster-artifacts" .Release.Name | lower }}
{{- end }}

{{/*
Mount options for the Dagster artifacts volume.

Deliberately NOT .Values.storage.mountOptions: that list is also consumed by the
backend's per-task PVs (backend-configmap MOUNT_OPTIONS -> task_pod.py), so a value
chosen there - e.g. idsfromsid/modefromsid, which derive mode and ownership from the
SMB security descriptor - would silently change this volume's permission semantics
and stop non-root analytical containers writing their results.

The Azure options below are what the azurefile CSI driver already appends when none
are given. Setting them explicitly means a driver change cannot alter them under us.
file_mode/dir_mode of 0777 is what makes the volume writable by an analytical image
running as ANY uid; uid=/gid= are deliberately omitted, since with 0777 they only
affect how ownership is reported.
*/}}
{{- define "dagsterArtifactsMountOptions" -}}
{{- $a := (.Values.fnDagster.artifacts | default dict) -}}
{{- if $a.mountOptions -}}
{{ toYaml $a.mountOptions }}
{{- else if .Values.storage.azure -}}
- file_mode={{ $a.fileMode | default "0777" }}
- dir_mode={{ $a.dirMode | default "0777" }}
- mfsymlinks
- nosharesock
- actimeo=30
{{- else if .Values.storage.nfs -}}
- hard
{{- end -}}
{{- end -}}

{{- define "awsStorageAccount" -}}
{{- if .Values.storage.aws }}
  {{- with .Values.storage.aws }}
    {{- if .accessPointId }}
      {{- printf "%s::%s" .fileSystemId .accessPointId | quote }}
    {{- else }}
      {{- .fileSystemId | quote }}
    {{- end }}
  {{- end }}
{{- end }}
{{- end -}}
{{- define "controllerCrdGroup" -}}
tasks.federatednode.com
{{- end -}}

{{/*
  Where kc-secrets is mounted in components that read credentials from disk rather than the
  environment.
*/}}
{{- define "kcSecretsMountPath" -}}
/etc/secrets/kc
{{- end -}}
