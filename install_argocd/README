# ArgoCD files

## argo-extra.yaml
This is used before the helm installation. It takes care of setting few pre requisite for adjusting argo's functionalities.

Configmap `config-map-helm-replace` will be referenced by the `lookup_values.yaml` file (see below) and aims to set the `--dry-run=server` argument when compiling helm templates.

This allows helm functions, such as `lookup`, to be interpreted correctly. Without it, it wouldn't be possible to inject existing k8s resources info and applying them to templates, returning errors.

The Cluster role just defines additional permissions to look for configmaps and secrets.

The ClusterRoleBinding, ties the ClusterRole to the `argocd-repo-server` service account.

## lookup_values.yaml
Is the effective values file for the argo helm chart. It basically adds an override on how the ingress health check is performed, always returning a successful status.

This is in order to avoid confusion in the UI.

## fn_application.yaml
Is a simple template to add the federatednode as an ArgoCD application. As a template, some of the values or values file reference are purely demonstrative, and they should be replaced with the desired values.
