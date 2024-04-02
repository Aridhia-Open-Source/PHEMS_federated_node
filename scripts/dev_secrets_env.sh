#!/bin/bash

###
# This script is for local development purposes.
# It aims to automate the port exposure of keycloak and db internal
# and sets the KEYCLOAK_SECRET and KEYCLOAK_ADMIN_PASSWORD in the
# dev.env file. This can be used to run the webserver with the debugger.
#
# Optional arg: .env file location. Defaults to <project>/webserver/dev.env
###

DEV_ENV_FILE=webserver/dev.env
if [[ -n $1 ]]; then
    DEV_ENV_FILE=$1
fi
KC_NAMESPACE=$(grep -oP '(?<=keycloak:\s).*' k8s/federated-node/dev.values.yaml)
TASK_NAMESPACE=$(grep -oP '(?<=tasks:\s).*' k8s/federated-node/dev.values.yaml)
BASE_NAMESPACE=$(helm list -A --output json | jq -r '.[] | select(.name=="federatednode")| .namespace')

if [[ -z $KC_NAMESPACE ]]; then
    KC_NAMESPACE=$(grep -oP '(?<=keycloak:\s).*' k8s/federated-node/values.yaml)
fi
if [[ -z $TASK_NAMESPACE ]]; then
    TASK_NAMESPACE=$(grep -oP '(?<=tasks:\s).*' k8s/federated-node/dev.values.yaml)
fi

PASS=$(kubectl get secret -n "${KC_NAMESPACE}" kc-secrets -o json | jq -r '.data.KEYCLOAK_ADMIN_PASSWORD' | base64 -d)
SEC=$(kubectl get secret -n "${KC_NAMESPACE}" kc-secrets -o json | jq -r '.data.KEYCLOAK_GLOBAL_CLIENT_SECRET' | base64 -d)

if grep 'KEYCLOAK_SECRET=' "$DEV_ENV_FILE"; then
    sed -i "s/KEYCLOAK_SECRET=.*/KEYCLOAK_SECRET=${SEC}/g" "$DEV_ENV_FILE"
else
    echo "KEYCLOAK_SECRET=${SEC}" >> "$DEV_ENV_FILE"
fi

if grep 'KEYCLOAK_ADMIN_PASSWORD=' "$DEV_ENV_FILE"; then
    sed -i "s/KEYCLOAK_ADMIN_PASSWORD=.*/KEYCLOAK_ADMIN_PASSWORD=${PASS}/g" "$DEV_ENV_FILE"
else
    echo "KEYCLOAK_ADMIN_PASSWORD=${PASS}" >> "$DEV_ENV_FILE"
fi

if grep 'TASK_NAMESPACE=' "$DEV_ENV_FILE"; then
    sed -i "s/TASK_NAMESPACE=.*/TASK_NAMESPACE=${TASK_NAMESPACE}/g" "$DEV_ENV_FILE"
else
    echo "TASK_NAMESPACE=${TASK_NAMESPACE}" >> "$DEV_ENV_FILE"
fi

if grep 'KEYCLOAK_NAMESPACE=' "$DEV_ENV_FILE"; then
    sed -i "s/KEYCLOAK_NAMESPACE=.*/KEYCLOAK_NAMESPACE=${KC_NAMESPACE}/g" "$DEV_ENV_FILE"
else
    echo "KEYCLOAK_NAMESPACE=${KC_NAMESPACE}" >> "$DEV_ENV_FILE"
fi

echo "run kubectl port-forward -n ${KC_NAMESPACE} svc/keycloak 8080"
echo "and kubectl port-forward -n ${BASE_NAMESPACE} svc/db 5432"
