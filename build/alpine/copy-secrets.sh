#!/bin/bash

set -e

copySecret(){
  secret=$1
  source_namespace=$2
  destination_namespace=$3
  echo "Copying $secret from $source_namespace to $destination_namespace"
  kubectl get secret "${secret}" -n "${source_namespace}" -o json | jq 'del(.metadata.namespace, .metadata.resourceVersion, .metadata.creationTimestamp, .metadata.uid, .metadata.annotations."meta.helm.sh/release-name", .metadata.annotations."meta.helm.sh/release-namespace", .labels.app."kub
ernetes.io/managed-by")' | kubectl apply -n "${destination_namespace}" -f -
}

yq -r '.secrets[] | .name + "|" + .namespace + "|" + .destination' "$CONFIG_PATH" | while IFS="|" read -r name ip destination; do
  [[ -z "$name" ]] && continue
  copySecret "$name" "$ip" "$destination"
done

cd ~

if [[ -n "$HAS_CERTS" ]]; then
  echo "setting environment"
  touch .env
  if [[ -n "$AZURE_CM" ]]; then
    kubectl get cm "$AZURE_CM" -o yaml | yq .data > .env
    echo "ENVIRONMENT=azure" >> .env
  elif [[ -n "$AWS_SECRET" ]]; then
    kubectl get secret "$AWS_SECRET" -o yaml | yq '.data | .[] |= @base64d' > .env
    echo "ENVIRONMENT=aws" >> .env
  fi
  sed -i "s/: /=/" .env

  cat .env
  python3 /usr/bin/certificate_issuer
  cat issuer.yaml
  kubectl apply -f issuer.yaml
fi
