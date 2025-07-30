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
ghcr.io/aridhia-open-source/federated_node_run:{{ include "image-tag" . }}
{{- end }}
{{- define "fn-alpine" -}}
ghcr.io/aridhia-open-source/alpine:{{ include "image-tag" . }}
{{- end }}
{{- define "image-tag" -}}
{{ (.Values.backend).tag | default .Chart.AppVersion }}
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

{{/*
Common db initializer, to use as element of initContainer
Just need to append the NEW_DB env var
*/}}
{{- define "createDBInitContainer" -}}
        - image: {{ include "fn-alpine" . }}
          name: dbinit
          command: [ "dbinit" ]
          imagePullPolicy: Always
          {{ include "nonRootSC" . }}
          env:
          - name: PGUSER
            valueFrom:
              configMapKeyRef:
                name: keycloak-config
                key: KC_DB_USERNAME
          - name: PGHOST
            valueFrom:
              configMapKeyRef:
                name: keycloak-config
                key: KC_DB_URL_HOST
          - name: PGPASSWORD
            valueFrom:
              secretKeyRef:
                name: {{.Values.db.secret.name}}
                key: {{.Values.db.secret.key}}
{{- end -}}

{{- define "dbPort" -}}
  {{ .Values.db.port | default 5432 | quote }}
{{- end -}}

{{- define "dbUser" -}}
  {{ .Values.db.user | default "admin" | quote }}
{{- end -}}

{{- define "dbKeycloakName" -}}
  {{ printf "fn_%s" (.Values.db.name | default "fndb") | quote }}
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
  {{- join ", " .Values.integrations.domains -}}
{{- end -}}
{{- define "cspDomainsSpace" -}}
  {{- join " " .Values.integrations.domains -}}
{{- end -}}
{{- define "kc_namespace" -}}
{{ ((.Values.global).namespaces).keycloak | default .Values.namespaces.keycloak }}
{{- end -}}
{{- define "tasks_namespace" -}}
{{ ((.Values.global).namespaces).tasks | default .Values.namespaces.tasks }}
{{- end -}}
{{- define "controller_namespace" -}}
{{ ((.Values.global).namespaces).controller | default .Values.namespaces.controller }}
{{- end -}}
{{- define "testsBaseUrl" }}
{{- if not .Values.local_development -}}
https://{{ .Values.host }}
{{- else -}}
http://backend.{{ .Release.Namespace }}.svc:{{ .Values.federatedNode.port }}
{{- end -}}
{{- end }}

{{- define "pvcName" -}}
{{ printf "flask-results-%s-pv-vc" (.Values.storage.capacity | default "10Gi") | lower }}
{{- end }}
{{- define "pvName" -}}
{{ printf "flask-results-%s-pv" (.Values.storage.capacity | default "10Gi") | lower }}
{{- end }}

{{- define "awsStorageAccount" -}}
{{- if .Values.storage.aws }}
  {{- with .Values.storage.aws }}
    {{- if .accessPointId }}
      {{- printf  "%s::%s" .fileSystemId .accessPointId | quote }}
    {{- else }}
      {{- .fileSystemId | quote }}
    {{- end }}
  {{- end }}
{{- end }}
{{- end -}}
