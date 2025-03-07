#!/bin/bash

set -e

CONFIG_DIR=${CONFIG_DIR:-"/etc/letsencrypt"}

cp "${CONFIG_DIR}"/live/"${DOMAIN}"/{privkey.pem,fullchain.pem} .
chmod 644 privkey.pem fullchain.pem

kubectl delete secret "${SSL_SECRET_NAME}" --ignore-not-found
kubectl create secret -n "${NAMESPACE}" tls "${SSL_SECRET_NAME}" --key privkey.pem --cert fullchain.pem
rm privkey.pem fullchain.pem
