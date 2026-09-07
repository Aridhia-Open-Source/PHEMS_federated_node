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
  A PersistentVolume over the Dagster artifacts storage, plus a claim on it in one
  namespace. Emitted once per namespace that mounts the volume: the run pod claims it
  in the release namespace, pipes task pods in the tasks namespace, and a claim cannot
  cross namespaces. Every copy points at the same underlying storage; only the volume
  handle has to differ, which CSI requires to be unique per PV.

  @param .ctx        root context
  @param .namespace  namespace to put the claim in
  @param .suffix     appended to the PV name, "" for the release namespace copy
  @param .subpath    EFS-only handle discriminator, "" for the release namespace copy
*/}}
{{- define "fn.dagsterArtifactsVolume" -}}
{{- $ctx := .ctx -}}
{{- $name := printf "%s%s" (include "dagsterArtifactsPVName" $ctx) .suffix -}}
apiVersion: v1
kind: PersistentVolume
metadata:
  name: {{ $name }}
spec:
  storageClassName: {{ include "dagsterArtifactsStorageClassName" $ctx }}
  capacity:
    storage: {{ $ctx.Values.storage.capacity }}
  accessModes:
    - ReadWriteMany
    - ReadOnlyMany
  persistentVolumeReclaimPolicy: Retain
  {{- with (include "dagsterArtifactsMountOptions" $ctx | trim) }}
  mountOptions:
{{ . | indent 4 }}
  {{- end }}
  {{ if $ctx.Values.storage.local }}
  local:
    path: {{ $ctx.Values.storage.local.artifacts }}
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/os
          operator: In
          values:
          - linux
  {{ else if $ctx.Values.storage.azure }}
  csi:
    driver: file.csi.azure.com
    volumeHandle: {{ printf "%s-dagster-artifacts%s" $ctx.Release.Name .suffix | lower }}
    readOnly: false
    volumeAttributes:
      shareName: {{ $ctx.Values.storage.azure.shareName }}
      {{- if $ctx.Values.storage.azure.resourceGroup }}
      resourceGroup: {{ $ctx.Values.storage.azure.resourceGroup }}
      {{- end }}
    nodeStageSecretRef:
      name: {{ $ctx.Values.storage.azure.secretName | default "azure-storage-secret" }}
      namespace: {{ $ctx.Release.Namespace }}
  {{ else if $ctx.Values.storage.aws }}
  csi:
    driver: efs.csi.aws.com
    {{- with $ctx.Values.storage.aws }}
    volumeHandle: {{ printf "%s:%s:%s" .fileSystemId $.subpath (.accessPointId | default "") | trimSuffix ":" | trimSuffix ":" | quote }}
    {{- end }}
  {{ else if $ctx.Values.storage.nfs }}
  nfs:
    server: {{ $ctx.Values.storage.nfs.url }}
    path: {{ $ctx.Values.storage.nfs.path }}
    readOnly: false
  {{ end }}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {{ include "dagsterArtifactsPVCName" $ctx }}
  namespace: {{ .namespace }}
spec:
  storageClassName: {{ include "dagsterArtifactsStorageClassName" $ctx }}
  volumeName: {{ $name }}
  resources:
    requests:
      storage: {{ $ctx.Values.storage.capacity }}
  accessModes:
    - ReadWriteMany
    - ReadOnlyMany
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
