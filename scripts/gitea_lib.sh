#!/usr/bin/env bash
###############################################################################
# Sourced by flux.sh: reach the dev cluster's Gitea as its admin.
# Uses GITEA_URL (default http://localhost:4000, the Tilt / portfwd port-forward) when it answers,
# else starts a port-forward of its own for the life of the script.
###############################################################################

GITEA_URL="${GITEA_URL:-http://localhost:4000}"
GITEA_ADMIN_USER="${GITEA_ADMIN_USER:-gitea_admin}"

gitea_connect() {
  if ! curl -fs -o /dev/null "$GITEA_URL/api/healthz"; then
    local port=14000
    echo "Gitea is not on $GITEA_URL, port-forwarding svc/gitea to localhost:$port"
    kubectl port-forward -n "$NAMESPACE" svc/gitea "$port:4000" >/dev/null 2>&1 &
    GITEA_PF_PID=$!
    trap 'kill "$GITEA_PF_PID" 2>/dev/null || true' EXIT
    GITEA_URL="http://localhost:$port"
    for _ in $(seq 30); do
      curl -fs -o /dev/null "$GITEA_URL/api/healthz" && break
      sleep 1
    done
  fi
  GITEA_ADMIN_PASSWORD="$(kubectl get secret gitea-admin -n "$NAMESPACE" -o jsonpath='{.data.password}' | base64 -d)"
  # Basic auth as a header, so the password never needs URL-encoding
  GITEA_AUTH_HEADER="Authorization: Basic $(printf '%s:%s' "$GITEA_ADMIN_USER" "$GITEA_ADMIN_PASSWORD" | base64 -w0)"
}

gitea_api() {
  local method="$1" path="$2"
  shift 2
  curl -fsS -X "$method" -H "$GITEA_AUTH_HEADER" -H "Content-Type: application/json" "$GITEA_URL/api/v1$path" "$@"
}

# gitea_ensure_repo NAME: create the admin's private repository NAME with Actions on. Prints "created" or "exists".
gitea_ensure_repo() {
  local name="$1"
  if gitea_api GET "/repos/$GITEA_ADMIN_USER/$name" >/dev/null 2>&1; then
    echo exists
    return
  fi
  gitea_api POST /user/repos -d "{\"name\": \"$name\", \"default_branch\": \"main\", \"private\": true}" >/dev/null
  gitea_api PATCH "/repos/$GITEA_ADMIN_USER/$name" -d '{"has_actions": true}' >/dev/null
  echo created
}

# gitea_git ARGS...: git with the admin's credentials for Gitea
gitea_git() {
  git -c "http.extraHeader=$GITEA_AUTH_HEADER" "$@"
}

gitea_repo_url() {
  echo "$GITEA_URL/$GITEA_ADMIN_USER/$1.git"
}
