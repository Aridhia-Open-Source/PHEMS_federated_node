#!/usr/bin/env bash
set -euo pipefail

# Bootstrap a Gitea server and Actions runner outside the application Helm release.
# The containers join kind's Docker network so Flux can reach Gitea before the node exists.

GITEA_CONTAINER="${GITEA_CONTAINER:-fn-demo-gitea}"
RUNNER_CONTAINER="${RUNNER_CONTAINER:-fn-demo-act-runner}"
GITEA_IMAGE="${GITEA_IMAGE:-gitea/gitea:28.1.0}"
RUNNER_IMAGE="${RUNNER_IMAGE:-gitea/act_runner:0.2.11}"
GITEA_ADMIN_USER="${GITEA_ADMIN_USER:-gitea_admin}"
GITEA_ADMIN_EMAIL="${GITEA_ADMIN_EMAIL:-admin@example.com}"
GITEA_DATA_DIR="${GITEA_DATA_DIR:-.local/gitea}"
GITEA_PASSWORD_FILE="$GITEA_DATA_DIR/admin-password"

if [ "${1:-up}" = down ]; then
  docker rm -f "$RUNNER_CONTAINER" "$GITEA_CONTAINER" 2>/dev/null || true
  echo "Stopped external Gitea and Actions runner (kept $GITEA_DATA_DIR)"
  exit 0
fi

mkdir -p "$GITEA_DATA_DIR" "$GITEA_DATA_DIR/runner"
chmod 700 "$GITEA_DATA_DIR"

if [ ! -s "$GITEA_PASSWORD_FILE" ]; then
  umask 077
  openssl rand -hex 24 > "$GITEA_PASSWORD_FILE"
  printf '\n' >> "$GITEA_PASSWORD_FILE"
fi
GITEA_ADMIN_PASSWORD="$(tr -d '\n' < "$GITEA_PASSWORD_FILE")"

docker network inspect kind >/dev/null

if ! docker container inspect "$GITEA_CONTAINER" >/dev/null 2>&1; then
  docker run -d --name "$GITEA_CONTAINER" \
    --network kind \
    --network-alias gitea-bootstrap \
    -p 4000:3000 \
    -p 2222:22 \
    -e USER_UID=1000 \
    -e USER_GID=1000 \
    -e GITEA__database__DB_TYPE=sqlite3 \
    -e GITEA__security__INSTALL_LOCK=true \
    -e GITEA__actions__ENABLED=true \
    -e GITEA__server__ROOT_URL=http://localhost:4000/ \
    -v "$PWD/$GITEA_DATA_DIR:/data" \
    "$GITEA_IMAGE" >/dev/null
else
  docker start "$GITEA_CONTAINER" >/dev/null 2>&1 || true
fi

for _ in $(seq 60); do
  curl -fsS http://localhost:4000/api/healthz >/dev/null && break
  sleep 1
done
curl -fsS http://localhost:4000/api/healthz >/dev/null

if ! docker exec --user git "$GITEA_CONTAINER" gitea admin user list --admin 2>/dev/null |
  awk -v user="$GITEA_ADMIN_USER" '$2 == user { found=1 } END { exit !found }'; then
  docker exec --user git "$GITEA_CONTAINER" gitea admin user create \
    --username "$GITEA_ADMIN_USER" \
    --password "$GITEA_ADMIN_PASSWORD" \
    --email "$GITEA_ADMIN_EMAIL" \
    --admin \
    --must-change-password=false >/dev/null
fi

AUTH_HEADER="Authorization: Basic $(printf '%s:%s' "$GITEA_ADMIN_USER" "$GITEA_ADMIN_PASSWORD" | base64 -w0)"

if ! docker container inspect "$RUNNER_CONTAINER" >/dev/null 2>&1; then
  docker run --rm --entrypoint /usr/local/bin/act_runner "$RUNNER_IMAGE" generate-config > "$GITEA_DATA_DIR/runner/config.yaml"
  sed -i 's|^  network:.*|  network: "kind"|' "$GITEA_DATA_DIR/runner/config.yaml"
  token="$(
    curl -fsS -X POST -H "$AUTH_HEADER" \
      http://localhost:4000/api/v1/admin/actions/runners/registration-token |
      python3 -c 'import json, sys; print(json.load(sys.stdin)["token"])'
  )"
  docker run -d --name "$RUNNER_CONTAINER" \
    --network kind \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$PWD/$GITEA_DATA_DIR/runner:/data" \
    -e GITEA_INSTANCE_URL=http://gitea-bootstrap:3000 \
    -e CONFIG_FILE=/data/config.yaml \
    -e GITEA_RUNNER_REGISTRATION_TOKEN="$token" \
    -e GITEA_RUNNER_NAME=fn-local \
    -e GITEA_RUNNER_LABELS=ubuntu-latest:docker://node:20-bookworm \
    "$RUNNER_IMAGE" >/dev/null
else
  docker start "$RUNNER_CONTAINER" >/dev/null 2>&1 || true
fi

echo "Gitea: http://localhost:4000"
echo "Repositories: http://localhost:4000/$GITEA_ADMIN_USER"
echo "Admin user: $GITEA_ADMIN_USER"
echo "Password file: $GITEA_PASSWORD_FILE"
echo "Actions runner: $RUNNER_CONTAINER"
