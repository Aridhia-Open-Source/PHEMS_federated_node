{{- /*
The parts every node config CRD shares (ADR 0032): group fn.aridhia.com, v1alpha1, namespaced, category fn
(`kubectl get fn` lists every kind), the status subresource and the Synced and Message columns.
Kept on uninstall, so removing the release never deletes the node config by cascade.
Called with (dict "kind" K "plural" P "spec" <the spec schema as YAML>).
The status is the operator's: synced, nexusId, message, observedGeneration, and a NodeSecret's sourceVersions.
Kopf keeps its own state in annotations, not status.
*/}}
{{- define "fn.crd" -}}
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: {{ .plural }}.fn.aridhia.com
  annotations:
    helm.sh/resource-policy: keep
spec:
  group: fn.aridhia.com
  scope: Namespaced
  names:
    kind: {{ .kind }}
    listKind: {{ .kind }}List
    plural: {{ .plural }}
    singular: {{ lower .kind }}
    categories:
      - fn
  versions:
    - name: v1alpha1
      served: true
      storage: true
      subresources:
        status: {}
      additionalPrinterColumns:
        - name: Synced
          type: boolean
          jsonPath: .status.synced
        - name: Message
          type: string
          jsonPath: .status.message
        - name: Age
          type: date
          jsonPath: .metadata.creationTimestamp
      schema:
        openAPIV3Schema:
          type: object
          required:
            - spec
          properties:
            spec:
              {{- .spec | nindent 14 }}
            status:
              type: object
              properties:
                synced:
                  type: boolean
                nexusId:
                  type: integer
                message:
                  type: string
                observedGeneration:
                  type: integer
                  format: int64
                sourceVersions:
                  type: object
                  description: NodeSecret only, source Secret name -> its resourceVersion last sent
                  additionalProperties:
                    type: string
{{- end -}}
