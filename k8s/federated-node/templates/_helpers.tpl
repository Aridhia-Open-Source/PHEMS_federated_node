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

{{- define "nexus-api-image" -}}
{{ printf "%s:%s" (.Values.nexus.api.image) ((.Values.nexus.api.tag) | default (include "image-tag" . | trim)) }}
{{- end }}

{{- define "nexus-ui-image" -}}
{{ printf "%s:%s" (.Values.nexus.ui.image) ((.Values.nexus.ui.tag) | default (include "image-tag" . | trim)) }}
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

{{- define "nexusDbName" -}}
  {{ .Values.nexus.api.db.name | quote }}
{{- end -}}

{{- define "nexusDbUser" -}}
  {{ .Values.nexus.api.db.user | quote }}
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
{{- define "quarantine_namespace" -}}
{{ ((.Values.global).namespaces).quarantine | default "fn-quarantine" }}
{{- end -}}
{{- define "secrets_namespace" -}}
{{ ((.Values.global).namespaces).secrets | default "fn-secrets" }}
{{- end -}}
{{- /* The service accounts that store secrets. Emitted as RoleBinding subjects. */ -}}
{{- define "nexusApiSubjects" -}}
- kind: ServiceAccount
  namespace: {{ .Release.Namespace }}
  name: nexus-api
{{- end -}}
{{- define "testsBaseUrl" }}
{{- if not .Values.local_development -}}
https://{{ .Values.host }}
{{- else -}}
{{ include "nexusApiUrl" . }}
{{- end -}}
{{- end }}

{{/*
The in-cluster URL Dagster, fncli and the smoke tests use to reach nexus-api. Defaults to the
release namespace so the chart is not pinned to a namespace called "fn";
set nexus.api.url explicitly to override (e.g. an external hostname).
*/}}
{{- define "nexusApiUrl" -}}
{{- if .Values.nexus.api.url -}}
{{ .Values.nexus.api.url }}
{{- else -}}
http://nexus-api.{{ .Release.Namespace }}.svc:{{ .Values.nexus.api.port }}
{{- end -}}
{{- end }}

{{/*
The in-cluster URL of the Dagster webserver, which serves the GraphQL API the FN API uses
to read and toggle sensors. Defaults to the dagster subchart's service in the release
namespace; set fnDagster.webserver.uri explicitly to override.
*/}}
{{- define "dagsterWebserverUri" -}}
{{- if .Values.fnDagster.webserver.uri -}}
{{ .Values.fnDagster.webserver.uri }}
{{- else -}}
http://{{ .Release.Name }}-dagster-webserver.{{ .Release.Namespace }}.svc:80
{{- end -}}
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

The Azure options below are what the azurefile CSI driver already appends when none
are given. Setting them explicitly means a driver change cannot alter them under us.
file_mode/dir_mode of 0777 is what makes the volume writable by an analytical image
running as ANY uid; uid=/gid= are deliberately omitted, since with 0777 they only
affect how ownership is reported.
mfsymlinks is deliberately not set: the volume holds partner output, and a symbolic link in it
could point out of its folder.
*/}}
{{- define "dagsterArtifactsMountOptions" -}}
{{- $a := (.Values.fnDagster.artifacts | default dict) -}}
{{- if $a.mountOptions -}}
{{ toYaml $a.mountOptions }}
{{- else if .Values.storage.azure -}}
- file_mode={{ $a.fileMode | default "0777" }}
- dir_mode={{ $a.dirMode | default "0777" }}
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

{{/*
  Where kc-secrets is mounted in components that read credentials from disk rather than the
  environment.
*/}}
{{- define "kcSecretsMountPath" -}}
/etc/secrets/kc
{{- end -}}

{{/*
Custom CA bundle for OUTBOUND TLS (customCA in values.yaml).

The CA in the Secret is added to the image's own system CAs, never substituted for
them: an init container concatenates the two into an emptyDir, and the workload's
tooling is pointed at that file. The Secret is mounted as a directory, never through
subPath, so the kubelet keeps it fresh; the combined file is only rebuilt when a pod
starts, hence the checksum annotation that makes `helm upgrade` roll the pods.
Everything is off unless customCA.secretName or customCA.pem is set.
*/}}
{{- define "fn.customCA.enabled" -}}
{{- if or (.Values.customCA).secretName (.Values.customCA).pem -}}true{{- end -}}
{{- end -}}

{{/* The Secret holding the CA: the one the operator named, else the one the chart renders. */}}
{{- define "fn.customCA.secretName" -}}
{{ (.Values.customCA).secretName | default "fn-custom-ca" }}
{{- end -}}

{{/* Where the combined bundle (system CAs + custom CA) is mounted in the workload. */}}
{{- define "fn.customCA.mountPath" -}}
/etc/fn-ca
{{- end -}}
{{- define "fn.customCA.bundleFile" -}}
{{ include "fn.customCA.mountPath" . }}/ca-bundle.crt
{{- end -}}

{{/*
Hash of the CA content, for the pod template annotation. Inline PEM: the PEM itself.
Named Secret: its data when the cluster can be read, otherwise its name and key, in
which case a changed Secret needs a rollout restart (see the README).

@param .ctx       root context
@param .namespace namespace the Secret lives in
*/}}
{{- define "fn.customCA.hash" -}}
{{- $ctx := .ctx -}}
{{- if $ctx.Values.customCA.secretName -}}
{{- $s := lookup "v1" "Secret" .namespace $ctx.Values.customCA.secretName | default dict -}}
{{- index (($s).data | default dict) $ctx.Values.customCA.key | default (printf "%s/%s" $ctx.Values.customCA.secretName $ctx.Values.customCA.key) | sha256sum -}}
{{- else -}}
{{- $ctx.Values.customCA.pem | sha256sum -}}
{{- end -}}
{{- end -}}

{{/* Pod template annotation: `checksum/custom-ca`. Call it only when enabled.
     @param .ctx root context, @param .namespace the workload's namespace */}}
{{- define "fn.customCA.annotations" -}}
checksum/custom-ca: {{ include "fn.customCA.hash" . | trunc 16 | quote }}
{{- end -}}

{{/* The Secret as a pod volume (no subPath use anywhere). Always lands as ca.crt. */}}
{{- define "fn.customCA.secretVolume" -}}
- name: custom-ca
  secret:
    secretName: {{ include "fn.customCA.secretName" . }}
    items:
      - key: {{ .Values.customCA.key }}
        path: ca.crt
{{- end -}}

{{/* Secret volume plus the emptyDir the init container writes the bundle to. */}}
{{- define "fn.customCA.volumes" -}}
{{ include "fn.customCA.secretVolume" . }}
- name: ca-bundle
  emptyDir: {}
{{- end -}}

{{/* The combined bundle, read-only, in the workload's own container. */}}
{{- define "fn.customCA.volumeMounts" -}}
- name: ca-bundle
  mountPath: {{ include "fn.customCA.mountPath" . }}
  readOnly: true
{{- end -}}

{{/* Env vars that point every client library the images use at the combined bundle:
     python requests, OpenSSL-based tools, curl, git. */}}
{{- define "fn.customCA.env" -}}
{{- range (list "REQUESTS_CA_BUNDLE" "SSL_CERT_FILE" "CURL_CA_BUNDLE" "GIT_SSL_CAINFO") }}
- name: {{ . }}
  value: {{ include "fn.customCA.bundleFile" $ }}
{{- end }}
{{- end -}}

{{/*
Init container that builds the bundle. It runs the workload's OWN image so the system
CAs it copies are the ones that workload would have used.

@param .ctx     root context
@param .image   the workload's image
@param .nonRoot true when the workload runs as non-root (the dagster image has no USER)
*/}}
{{- define "fn.customCA.initContainer" -}}
- name: build-ca-bundle
  image: {{ .image | quote }}
  imagePullPolicy: {{ .ctx.Values.pullPolicy }}
  securityContext:
    allowPrivilegeEscalation: false
    {{- if .nonRoot }}
    runAsNonRoot: true
    {{- end }}
    seccompProfile:
      type: RuntimeDefault
    capabilities:
      drop: [ "ALL" ]
  command:
    - sh
    - -c
    - |
      set -eu
      sys=""
      for f in /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/cert.pem; do
        if [ -s "$f" ]; then sys="$f"; break; fi
      done
      if [ -z "$sys" ]; then
        echo "no system CA bundle found in this image; refusing to build a bundle of the custom CA alone" >&2
        exit 1
      fi
      if [ ! -s /custom-ca/ca.crt ]; then
        echo "the custom CA is empty" >&2
        exit 1
      fi
      { cat "$sys"; echo; cat /custom-ca/ca.crt; echo; } > /ca-bundle/ca-bundle.crt
  volumeMounts:
    - name: custom-ca
      mountPath: /custom-ca
      readOnly: true
    - name: ca-bundle
      mountPath: /ca-bundle
{{- end -}}

{{/*
Proxy for OUTBOUND calls (proxy in values.yaml): the standard environment variables, in
upper and lower case because tools differ in which they read. Everything is off unless
proxy.httpProxy or proxy.httpsProxy is set. NO_PROXY always starts with the in-cluster
addresses, so calls between the node's own services skip the proxy; the operator's
proxy.noProxy follows. The kubelet expands $(KUBERNETES_SERVICE_HOST) in the value.
*/}}
{{- define "fn.proxy.enabled" -}}
{{- if or (.Values.proxy).httpProxy (.Values.proxy).httpsProxy -}}true{{- end -}}
{{- end -}}

{{- define "fn.proxy.noProxy" -}}
localhost,127.0.0.1,.svc,.svc.cluster.local,.cluster.local,$(KUBERNETES_SERVICE_HOST)
{{- with .Values.proxy.noProxy -}},{{ . }}{{- end -}}
{{- end -}}

{{/* Only the variables that have a value; NO_PROXY always has one. */}}
{{- define "fn.proxy.env" -}}
{{- $vars := dict "HTTPS_PROXY" .Values.proxy.httpsProxy "HTTP_PROXY" .Values.proxy.httpProxy "NO_PROXY" (include "fn.proxy.noProxy" .) }}
{{- range $name, $value := $vars }}
{{- if $value }}
{{- range (list $name (lower $name)) }}
- name: {{ . }}
  value: {{ $value | quote }}
{{- end }}
{{- end }}
{{- end }}
{{- end -}}

{{/*
The Dagster container context for run pods (JSON). The code server hands it to the
K8sRunLauncher with every run, so the pods that clone and push git and deliver
results get the same env as the code server; with customCA, the same volumes and
init container too. Task (pipes) pods are not given it: they run partner code and have
no outbound access. Call it only when customCA or the proxy is enabled.

@param .ctx   root context
@param .image the dagster image
*/}}
{{- define "fn.runContainerContext" -}}
{{- $ctx := .ctx -}}
{{- $k8s := dict -}}
{{- $env := list -}}
{{- if include "fn.customCA.enabled" $ctx -}}
{{- $env = include "fn.customCA.env" $ctx | fromYamlArray -}}
{{- $_ := set $k8s "volumes" (include "fn.customCA.volumes" $ctx | fromYamlArray) -}}
{{- $_ := set $k8s "volume_mounts" (include "fn.customCA.volumeMounts" $ctx | fromYamlArray) -}}
{{- $_ := set $k8s "run_k8s_config" (dict "pod_spec_config" (dict "init_containers" (include "fn.customCA.initContainer" (dict "ctx" $ctx "image" .image) | fromYamlArray))) -}}
{{- end -}}
{{- if include "fn.proxy.enabled" $ctx -}}
{{- $env = concat $env (include "fn.proxy.env" $ctx | fromYamlArray) -}}
{{- end -}}
{{- $_ := set $k8s "env" $env -}}
{{- dict "k8s" $k8s | toJson -}}
{{- end -}}
