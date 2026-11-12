#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# First-time dev setup: copies the example config into place (never overwriting
# a file that exists) and asks for the first Keycloak user if .dev.env has none.
###############################################################################

cd "$(dirname "$0")/.."

copy_if_missing() {
  if [ -e "$2" ]; then
    echo "$2 exists, left alone"
  else
    cp "$1" "$2"
    echo "$2 created from $1"
  fi
}

# Writes KEY='value' over an empty KEY= line in .dev.env. Single quotes keep any character
# in the value safe when .dev.env is sourced.
set_if_empty() {
  local key="$1" value="$2"
  if ! grep -qE "^${key}=(''|\"\")?$" .dev.env; then
    echo "$key is already set in .dev.env, left alone"
    return
  fi
  if [[ "$value" == *"'"* ]]; then
    echo "$key must not contain a single quote" >&2
    exit 1
  fi
  VALUE="$value" awk -v key="$key" 'index($0, key "=") == 1 { print key "=\x27" ENVIRON["VALUE"] "\x27"; next } { print }' \
    .dev.env > .dev.env.tmp
  mv .dev.env.tmp .dev.env
  echo "$key written to .dev.env"
}

copy_if_missing .dev.env.example .dev.env
copy_if_missing k8s/federated-node/dev.example.values.yml k8s/federated-node/dev.values.yaml

if grep -qE "^KEYCLOAK_FIRST_USER_EMAIL=(''|\"\")?$" .dev.env; then
  read -r -p "First Keycloak user email: " email
  set_if_empty KEYCLOAK_FIRST_USER_EMAIL "$email"
fi

if grep -qE "^KEYCLOAK_FIRST_USER_PASSWORD=(''|\"\")?$" .dev.env; then
  read -r -s -p "First Keycloak user password: " password
  echo
  set_if_empty KEYCLOAK_FIRST_USER_PASSWORD "$password"
fi

echo
echo "Done. Next: make cluster-up, then make deploy"
