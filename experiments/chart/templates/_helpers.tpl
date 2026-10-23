{{/*
A password, base64-encoded: the existing Secret's value if there is one, otherwise a new
random one. Copied from fn.dbPassword in the federated-node chart.
*/}}
{{- define "experiments.password" -}}
{{- $existing := lookup "v1" "Secret" .namespace .name -}}
{{- index (($existing).data | default dict) .key | default (randAlphaNum 24 | b64enc) -}}
{{- end -}}
