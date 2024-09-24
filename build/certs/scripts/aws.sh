#!/bin/bash

## This is not tested yet, it's just to provide a base to work with
CERTBOT_FOLDER=~/.aws/config
export AWS_CONFIG_FILE="${CERTBOT_FOLDER}/aws.ini"

mkdir -p "${CERTBOT_FOLDER}"

cat <<EOF> "${CERTBOT_FOLDER}/aws.ini"
[default]
aws_access_key_id=${AWS_ACCESS_KEY_ID}
aws_secret_access_key=${AWS_SECRET_ACCESS_KEY}
EOF

chmod 600 "${CERTBOT_FOLDER}/aws.ini"

certbot certonly \
  --dns-route53 \
  -d "${DOMAIN}"

./apply_secret.sh
