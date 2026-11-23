#!/usr/bin/env bash
# Writes a filled Postman environment and a collection built from nexus-api's OpenAPI spec, both
# gitignored, for project/QA/README.md ("Making HTTP calls"). Variables come from .postman.env
# (baseUrl, username, password) when it exists, otherwise from the dev cluster: the first
# Keycloak user from the Secret named by the release's firstUserSecret, nexus-api on the
# `mise run portfwd` / Tilt port-forward.
set -euo pipefail

dir=project/QA/postman
env_out=$dir/fn.local.postman_environment.json
collection_out=$dir/fn.local.postman_collection.json

if [ -f .postman.env ]; then
  # Plain KEY=VALUE, not sourced, so a password keeps any $, quote or space
  while IFS='=' read -r key value; do
    case "$key" in baseUrl | username | password) printf -v "$key" '%s' "$value" ;; esac
  done < .postman.env
  : "${baseUrl:?.postman.env must set baseUrl}" "${username:?.postman.env must set username}" \
    "${password:?.postman.env must set password}"
  source=.postman.env
else
  : "${RELEASE_NAME:?RELEASE_NAME is not set (.dev.env), and there is no .postman.env}" "${NAMESPACE:?NAMESPACE is not set (.dev.env)}"
  first_user=$(helm get values "$RELEASE_NAME" -n "$NAMESPACE" -o json | jq -e '.firstUserSecret') \
    || { echo "release $RELEASE_NAME in $NAMESPACE has no firstUserSecret" >&2; exit 1; }
  secret=$(jq -er .name <<<"$first_user")
  key=$(jq -er .passKey <<<"$first_user")
  username=$(jq -er .email <<<"$first_user")
  password=$(kubectl get secret "$secret" -n "$NAMESPACE" -o go-template="{{index .data \"$key\" | base64decode}}")
  [ -n "$password" ] || { echo "Secret $secret in $NAMESPACE has no $key" >&2; exit 1; }
  baseUrl=http://localhost:5000
  source="the $RELEASE_NAME release"
fi

jq --arg baseUrl "$baseUrl" --arg username "$username" --arg password "$password" \
  '.values |= map(.value = ({baseUrl: $baseUrl, username: $username, password: $password}[.key] // .value))' \
  "$dir/fn.postman_environment.json" > "$env_out"
python3 scripts/postman_collection.py nexus/api/openapi.json "$dir/prerequest.js" "$collection_out"

echo "From $source ($baseUrl, $username). Import both into Postman and select the environment:"
echo "  $env_out"
echo "  $collection_out"
