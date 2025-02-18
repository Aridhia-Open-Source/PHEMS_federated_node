#!/bin/bash

CONFIG_DIR=${CONFIG_DIR:-"/etc/letsencrypt"}

mkdir -p "${CERTBOT_FOLDER}"

. "${VENV_DIR}"/bin/activate

set -e

cat <<EOF> "${CERTBOT_FOLDER}/azure.ini"
dns_azure_sp_client_id = ${DNS_SP_ID}
dns_azure_sp_client_secret = ${DNS_SP_SECRET}
dns_azure_tenant_id = ${AZ_DIRECTORY_ID}
dns_azure_zone1 = ${DOMAIN}:/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/rg-subscription/providers/Microsoft.Network/dnszones/${DOMAIN}
EOF

chmod 600 "${CERTBOT_FOLDER}/azure.ini"

certbot certonly -v \
    --key-type rsa \
    --authenticator dns-azure \
    --preferred-challenges dns \
    --noninteractive \
    --agree-tos \
    --dns-azure-config "${CERTBOT_FOLDER}"/azure.ini \
    --domain "*.${DOMAIN}" \
    --redirect \
    --email "${EMAIL_CERT}" \
    --work-dir . \
    --config-dir "${CONFIG_DIR}" \
    --preferred-chain='ISRG Root X1'

/app/scripts/apply_secret.sh
