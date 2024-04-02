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
Create the name of the service account to use
*/}}
{{- define "federated-node.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "federated-node.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Common db initializer, to use as element of initContainer
Just need to append the NEW_DB env var
*/}}
{{- define "createDBInitContainer" -}}
        - image: alpine
          name: dbinit
          command: [
            'sh', '-c', '/scripts/dbinit.sh'
          ]
          volumeMounts:
            - name: db-init
              mountPath: /scripts/dbinit.sh
              subPath: dbinit.sh
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
                {{ if .Values.db.secret }}
                name: {{.Values.db.secret.name}}
                key: {{.Values.db.secret.key}}
                {{ else }}
                name: kc-secrets
                key: KC_DB_PASSWORD
                {{ end }}
{{- end -}}

{{- define "dbInitVolume" -}}
        - name: db-init
          configMap:
            name: db-initializer-configmap
            defaultMode: 0777
            items:
            - key: dbinit.sh
              path: dbinit.sh
{{- end -}}

{{- define "randomPass" -}}
{{ randAlphaNum 24 | b64enc | quote }}
{{- end -}}

{{- define "randomSecret" -}}
{{ randAlphaNum 24 | b64enc | quote }}
{{- end -}}
