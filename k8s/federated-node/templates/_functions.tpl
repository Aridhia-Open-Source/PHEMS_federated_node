{{/*
  Wrapper for lookup, for objects the chart reads but does not create. Returns
  nothing when the cluster is unreachable (`helm template`, client-side --dry-run),
  where a valid values file must still render; otherwise a missing object fails the
  render, naming it and what it was wanted for.

  @param .ctx       root context
  @param .entity    k8s object to fetch, i.e "Secret" or "ConfigMap"
  @param .namespace entity's namespace
  @param .name      entity's name
  @param .purpose   optional: what it is needed for, for the message
*/}}
{{- define "lookupOrError" -}}
  {{- $obj := lookup "v1" .entity .namespace .name | default dict -}}
  {{- if $obj -}}
    {{ $obj | toYaml | nindent 0 }}
  {{- else if ne (include "fn.clusterReachable" .ctx) "true" -}}
  {{- else -}}
    {{ fail (printf "%s %q was not found in namespace %q.%s\n\nIt is an external input this chart cannot generate, so create it in %s and install again.\n" .entity .name .namespace (.purpose | default "" | printf " %s" | trimSuffix " ") .namespace) }}
  {{- end -}}
{{- end -}}

{{/*
  Re-emit an existing secret into another namespace.

  @param .ctx        root context
  @param .name       secret name
  @param .target     namespace to copy into
*/}}
{{- define "fn.copySecret" -}}
{{- with include "lookupOrError" (dict "ctx" .ctx "entity" "Secret" "namespace" .ctx.Release.Namespace "name" .name "purpose" (printf "It is copied from there into namespace %q." .target)) | fromYaml }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ .metadata.name }}
  namespace: {{ $.target }}
data:
{{ toYaml .data | indent 2 }}
type: {{ .type }}
---
{{- end }}
{{- end -}}
