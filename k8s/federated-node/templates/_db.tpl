{{/*
Resolve a database password, base64-encoded for a Secret's `data`: db.passwords.* ->
an existing Secret in the given namespaces -> a random one if `generate`. Reusing the
existing Secret is what stops an upgrade rotating a password Postgres already has.
Returns "" if nothing is found and `generate` is false; the caller then emits nothing.

Alphanumeric only - the password goes unquoted into a postgresql:// URI and a JDBC URL.

args: dict { namespaces: [ns...], name: <secret>, key: <key>, plain: <string>, generate: <bool> }
*/}}
{{- define "fn.dbPassword" -}}
{{- $name := .name -}}
{{- $key := .key -}}
{{- $value := "" -}}
{{- if .plain -}}
  {{- $value = .plain | toString | b64enc -}}
{{- else -}}
  {{- range $ns := .namespaces -}}
    {{- if not $value -}}
      {{- $existing := lookup "v1" "Secret" $ns $name -}}
      {{- $value = index (($existing).data | default dict) $key | default "" -}}
    {{- end -}}
  {{- end -}}
  {{- if and (not $value) .generate -}}
    {{- $value = randAlphaNum 24 | b64enc -}}
  {{- end -}}
{{- end -}}
{{- $value -}}
{{- end -}}

{{/*
"true" only when `lookup` can reach an API server. `helm template` and client-side
--dry-run return nil from every lookup, so cluster-state checks must skip there
rather than fail a valid render.
*/}}
{{- define "fn.clusterReachable" -}}
{{- if lookup "v1" "Namespace" "" "kube-system" -}}true{{- end -}}
{{- end -}}

{{- define "dbHost" -}}
{{- .Values.db.host -}}
{{- end -}}

{{- define "dbPort" -}}
{{- .Values.db.port | default 5432 -}}
{{- end -}}

{{/*
Dagster's database, derived from the dagster subchart's own values: Helm cannot
template a subchart value from the parent, so that block is the single source and
this chart reads it back. There is deliberately no fnDagster.db.
*/}}
{{- define "dagsterDbHost" -}}
{{- ((.Values.dagster).postgresql).postgresqlHost | default (include "dbHost" .) -}}
{{- end -}}

{{- define "dagsterDbName" -}}
{{- ((.Values.dagster).postgresql).postgresqlDatabase | default "dagster" -}}
{{- end -}}

{{- define "dagsterDbUser" -}}
{{- ((.Values.dagster).postgresql).postgresqlUsername | default "dagster_admin" -}}
{{- end -}}

{{/* The subchart reads this secret itself. Its name is yours to choose via
     global.postgresqlSecretName; the key is not - the subchart hardcodes
     postgresql-password in its daemon, webserver and migrate-job templates. */}}
{{- define "dagsterDbSecretName" -}}
{{- ((.Values.global).postgresqlSecretName) | default "dagster-postgresql-secret" -}}
{{- end -}}

{{- define "dagsterDbSecretKey" -}}
postgresql-password
{{- end -}}
