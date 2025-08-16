{{/*
  Wrapper for lookup. It will raise an error message
  saying a certain entity is not found

  @param .entity    k8s object to fetch, i.e "ConfigMap"
  @param .namespace entity's namespace
  @param .name      entity's name
*/}}
{{- define "lookupOrError" -}}
  {{ $obj := lookup "v1" .entity .namespace .name | default dict}}
  {{- if $obj }}
    {{ $obj | toYaml  | nindent 0 }}
  {{- else }}
    {{ fail (printf "%s %s not found in namespace %s" .entity .name .namespace) }}
  {{- end }}
{{- end -}}
