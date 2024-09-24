#!/bin/bash

sudo cp /etc/letsencrypt/live/"${DOMAIN}"/{privkey.pem,fullchain.pem} .
sudo chmod 644 privkey.pem fullchain.pem

kubectl delete secret ui-ssl --ignore-not-found
kubectl create secret -n "${NAMESPACE}" tls ui-ssl --key privkey.pem --cert fullchain.pem
kubectl rollout restart deployment nginx-ingress
rm privkey.pem fullchain.pem

kubectl get secret ui-ssl -o yaml | sed '/namespace\|creationTimestamp\|resourceVersion\|uid:/d;' | kubectl apply -n "${KEYCLOAK_NAMESPACE}" -f -
