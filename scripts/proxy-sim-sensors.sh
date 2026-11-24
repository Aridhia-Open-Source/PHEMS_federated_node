#!/usr/bin/env bash
set -euo pipefail

###################################################################################
# Federated Node - the Dagster pull-request pipeline behind a TLS-intercepting proxy
#
# Runs on the kind dev cluster, with the in-cluster Gitea standing in for an outside git host.
#
#   proxysim  mitmproxy in its own namespace, a regular proxy at http://proxysim.proxysim.svc:8080.
#             It re-signs every HTTPS connection with its own CA, as a corporate proxy does.
#   gitea.proxysim.test
#             an outside-looking name for Gitea that only the proxy knows: mitmproxy answers TLS
#             for it with its CA and forwards the requests to http://gitea.<ns>.svc:4000. The
#             node's in-cluster addresses skip the proxy (NO_PROXY), so the test project is
#             registered under this name; everything it does with Gitea has to cross the proxy.
#
# Three runs, each a deploy of the release with the proxy set (through a generated.values.yaml,
# as scripts/configure.sh writes it) and one cert mode:
#   none    no customCA                  expected: the pipeline fails with a TLS/certificate error
#   wrong   customCA = an unrelated CA   expected: the same
#   right   customCA = mitmproxy's CA    expected: the merged PR is ingested, the task runs and the
#                                        results branch and results PR appear in Gitea
#
#   ./scripts/proxy-sim-sensors.sh up                   # mitmproxy in the proxysim namespace (keeps its CA)
#   ./scripts/proxy-sim-sensors.sh probe                # curl through the proxy: fails without the CA, works with it
#   ./scripts/proxy-sim-sensors.sh deploy <none|wrong|right>
#                                                       # scripts/deploy.sh with the proxy and that CA
#   ./scripts/proxy-sim-sensors.sh setup                # the proxysim project, its Gitea repos and secrets (kubectl apply)
#   ./scripts/proxy-sim-sensors.sh pr                   # start the sensors, open and merge one watched PR (fncli open-pr)
#   ./scripts/proxy-sim-sensors.sh status               # the project, TLS errors in the logs, what crossed the proxy
#   ./scripts/proxy-sim-sensors.sh down                 # remove the project, proxysim and the CA secret, and put back
#                                                       # your own generated files (its Gitea repos stay)
#
# Run it as `mise x -- ./scripts/proxy-sim-sensors.sh ...` (deploy.sh needs fncli on the PATH). It needs
# the port-forwards (mise run portfwd; not Tilt, which deploys without the proxy) and dagster/.venv
# (mise run setup), or FNCLI_PYTHON set to a python that runs fncli. fncli calls Gitea under its outside
# name, so setup, pr and status reach it as the node does: through proxysim (port-forwarded to the
# host for the call), trusting its CA. Setup also has the node call Gitea, so run it after `deploy right`.
# The node config is config/proxysim/proxysim.yaml (ADR 0032). Generated, and gitignored with the rest of bootstrap/: the
# context bootstrap/proxysim-context.yaml (a copy of the example one) and, in bootstrap/proxysim/, mitmproxy's
# CA, the wrong one, and your own .generated.env and generated.values.yaml while `deploy` has set them aside.
# After `down`, `mise run deploy` puts the release back without the proxy.
####################################################################################

cd "$(dirname "$0")/.."
ROOT="$PWD"

COMMAND="${1:-}"
MODE="${2:-}"

source scripts/load_env.sh
source scripts/custom_ca.sh
NS_PROXY="proxysim"
DIR="${ROOT}/bootstrap/proxysim"
SAVED="${DIR}/saved"
GENERATED_ENV=.generated.env
GENERATED_VALUES=k8s/federated-node/generated.values.yaml
IMAGE="${PROXYSIM_IMAGE:-mitmproxy/mitmproxy:latest}"
CLUSTER="${CLUSTER_NAME:-fn}"
PROXY_URL="http://proxysim.${NS_PROXY}.svc:8080"
HOST="gitea.proxysim.test"
GITEA_SVC="http://gitea.${NAMESPACE}.svc:4000"
FNCLI_PYTHON="${FNCLI_PYTHON:-$ROOT/dagster/.venv/bin/python}"
# The node config is committed (its host is HOST); the context is the example one, copied like any fncli context.
CONFIG_FILE="${ROOT}/config/proxysim/proxysim.yaml"
OPERATOR_NAMESPACE="${OPERATOR_NAMESPACE:-fn-operator}"
CONTEXT_FILE="${ROOT}/bootstrap/proxysim-context.yaml"
PROJECT=proxysim
PROXY_LOCAL_PORT="${PROXYSIM_LOCAL_PORT:-18080}"
# What a client prints when it does not trust the certificate it was shown.
TLS_ERRORS='x509:|certificate verify failed|CERTIFICATE_VERIFY_FAILED|SSL certificate problem|unknown authority|SSLError'

mkdir -p "$DIR"
cp "${ROOT}/bootstrap/examples/context.yaml" "$CONTEXT_FILE"

# Without .dev.env's PYTHONPATH=./app, whose secrets.py hides the standard library's.
fncli() {
  (cd "$ROOT/dagster" && env -u PYTHONPATH FNCLI_CONTEXT="$CONTEXT_FILE" NAMESPACE="$NAMESPACE" \
    "$FNCLI_PYTHON" -m fncli "$@")
}

# Runs the rest of the line (a command or a function) with its HTTPS calls going through proxysim and
# trusting its CA, as the node's pods do. The proxy is port-forwarded to the host for the call. ALL_PROXY,
# not HTTPS_PROXY: requests and curl honour it, and the Kubernetes client (which fncli reads secrets with,
# and which ignores NO_PROXY) does not, so it still reaches the cluster directly.
via_proxy() {
  local forward rc=0 i
  kubectl port-forward -n "$NS_PROXY" svc/proxysim "${PROXY_LOCAL_PORT}:8080" >/dev/null &
  forward=$!
  for i in $(seq 40); do
    curl -s -o /dev/null "http://localhost:${PROXY_LOCAL_PORT}/" && break
    [ "$i" -lt 40 ] || { kill "$forward"; echo "proxysim is not reachable on localhost:${PROXY_LOCAL_PORT}: run up first" >&2; return 1; }
    sleep 0.5
  done
  # Not in a `||` list: that would switch off set -e for the commands inside
  set +e
  (
    set -e
    export ALL_PROXY="http://localhost:${PROXY_LOCAL_PORT}" all_proxy="http://localhost:${PROXY_LOCAL_PORT}"
    export NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1
    export REQUESTS_CA_BUNDLE="${DIR}/mitmproxy-ca-cert.pem" CURL_CA_BUNDLE="${DIR}/mitmproxy-ca-cert.pem"
    "$@"
  )
  rc=$?
  set -e
  kill "$forward" 2>/dev/null || true
  return "$rc"
}

# mitmproxy's CA, made once by mitmproxy itself so it is a CA it accepts.
make_ca() {
  [ -s "${DIR}/mitmproxy-ca.pem" ] && return 0
  docker run --rm -v "${DIR}:/out" --entrypoint sh "$IMAGE" -c \
    'timeout 5 mitmdump --set confdir=/tmp/c >/dev/null 2>&1; cp /tmp/c/mitmproxy-ca.pem /tmp/c/mitmproxy-ca-cert.pem /out/; chown '"$(id -u):$(id -g)"' /out/mitmproxy-ca*.pem'
  chmod 600 "${DIR}/mitmproxy-ca.pem"
}

up() {
  make_ca
  kubectl create namespace "$NS_PROXY" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl create secret generic proxysim-ca -n "$NS_PROXY" --from-file="${DIR}/mitmproxy-ca.pem" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kind load docker-image "$IMAGE" --name "$CLUSTER" >/dev/null
  # lazy: mitmproxy only connects upstream once it has the request, so it never has to resolve
  # gitea.proxysim.test, which map_remote has turned into Gitea's service address by then.
  kubectl apply -n "$NS_PROXY" -f - >/dev/null <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: proxysim
spec:
  replicas: 1
  selector:
    matchLabels: {app: proxysim}
  template:
    metadata:
      labels: {app: proxysim}
    spec:
      containers:
        - name: mitmproxy
          image: ${IMAGE}
          imagePullPolicy: Never
          env:
            # Otherwise its log reaches kubectl logs in late blocks
            - {name: PYTHONUNBUFFERED, value: "1"}
            # and URLs cut to fit an 80-column terminal
            - {name: COLUMNS, value: "400"}
          command: [sh, -c]
          args:
            - >-
              mkdir -p /tmp/conf && cp /ca/mitmproxy-ca.pem /tmp/conf/ &&
              exec mitmdump --set confdir=/tmp/conf --listen-port 8080 --set block_global=false
              --set connection_strategy=lazy
              --map-remote '|^https://${HOST//./\\.}(:443)?/|${GITEA_SVC}/'
          ports:
            - containerPort: 8080
          volumeMounts:
            - {name: ca, mountPath: /ca, readOnly: true}
      volumes:
        - name: ca
          secret: {secretName: proxysim-ca}
---
apiVersion: v1
kind: Service
metadata:
  name: proxysim
spec:
  selector: {app: proxysim}
  ports:
    - {port: 8080, targetPort: 8080}
EOF
  kubectl rollout status deployment/proxysim -n "$NS_PROXY" --timeout=120s >/dev/null
}

# A throwaway pod in the release namespace with the proxy set, as the node's pods have it.
probe() {
  local pod=proxysim-probe out
  kubectl delete pod "$pod" -n "$NAMESPACE" --ignore-not-found >/dev/null
  kubectl run "$pod" -n "$NAMESPACE" --image="localhost:5001/alpine-fn:latest" --restart=Never \
    --env="HTTPS_PROXY=${PROXY_URL}" --env="NO_PROXY=.svc" --command -- sleep 300 >/dev/null
  kubectl wait --for=condition=Ready "pod/${pod}" -n "$NAMESPACE" --timeout=90s >/dev/null
  kubectl exec -i "$pod" -n "$NAMESPACE" -- sh -c 'cat > /tmp/ca.crt' < "${DIR}/mitmproxy-ca-cert.pem"
  echo "--- without the CA (expected: a certificate error)"
  if out="$(kubectl exec "$pod" -n "$NAMESPACE" -- curl -sS "https://${HOST}/api/v1/version" 2>&1)"; then
    echo "$out"; echo "FAIL: worked without the CA"; return 1
  fi
  echo "$out"
  grep -q -E "$TLS_ERRORS" <<<"$out" || { echo "FAIL: not a certificate error"; return 1; }
  echo "--- with the CA (expected: Gitea's version)"
  kubectl exec "$pod" -n "$NAMESPACE" -- curl -sS --fail --cacert /tmp/ca.crt "https://${HOST}/api/v1/version"
  echo
  kubectl delete pod "$pod" -n "$NAMESPACE" --wait=false >/dev/null
  echo "--- mitmproxy's log"
  kubectl logs deployment/proxysim -n "$NS_PROXY" --tail=10
}

# Sets your own generated files aside, once, so deploy.sh loads neither: .generated.env would
# override the CA this run passes, and its proxy is not this one. `down` puts them back.
set_aside() {
  [ ! -d "$SAVED" ] || return 0
  mkdir -p "$SAVED"
  local f
  for f in "$GENERATED_ENV" "$GENERATED_VALUES"; do
    if [ -f "$f" ]; then mv "$f" "${SAVED}/$(basename "$f")"; fi
  done
}

# The release with the proxy set and the mode's CA as customCA. FORCE_OWNER=1 passes through.
deploy() {
  local ca=""
  case "$MODE" in
    none) ;;
    wrong)
      openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=proxysim-wrong-ca \
        -addext basicConstraints=critical,CA:TRUE -addext keyUsage=critical,keyCertSign \
        -keyout /dev/null -out "${DIR}/wrong-ca.crt" 2>/dev/null
      ca="${DIR}/wrong-ca.crt" ;;
    right) ca="${DIR}/mitmproxy-ca-cert.pem" ;;
    *) echo "Mode is none, wrong or right" >&2; exit 1 ;;
  esac
  set_aside
  {
    echo "# Generated by scripts/proxy-sim-sensors.sh for its test run; its down puts yours back."
    echo "proxy:"
    echo "  httpProxy: \"$PROXY_URL\""
    echo "  httpsProxy: \"$PROXY_URL\""
    if [ -n "$ca" ]; then
      echo "customCA:"
      echo "  secretName: $CUSTOM_CA_SECRET"
      echo "  key: ca.crt"
    fi
  } > "$GENERATED_VALUES"
  CUSTOM_CA_FILE="$ca" ./scripts/deploy.sh
}

# The project, its repositories and secrets, and the Gitea repos and OAuth apps behind them. The demo's
# dataset (fncli experiment setup demo) is already on the node.
setup() {
  fncli gitea setup -f "$CONFIG_FILE"
  kubectl apply -f "$CONFIG_FILE"
  kubectl wait --for=jsonpath='{.status.synced}'=true --timeout=180s -f "$CONFIG_FILE"
  fncli start-sensor --group all
}

# Starts the sensors (a no-op when running), then opens and merges one watched pull request.
pr() {
  fncli start-sensor --group all
  fncli open-pr --merge --project "$PROJECT"
}

gitea_get() {
  local password
  password="$(kubectl get secret gitea-admin -n "$NAMESPACE" -o jsonpath='{.data.password}' | base64 -d)"
  curl -sS --fail -u "gitea_admin:${password}" "https://${HOST}/api/v1/$1"
}

status() {
  echo "--- the project's pull requests, tasks and results"
  fncli project-show --project "$PROJECT" | jq '{pull_requests: [.pull_requests[]? | {number, status, task_id}],
    tasks: [.tasks[]? | {id, status}], results: [.results[]? | {task_id, step, status, number}]}' 2>/dev/null \
    || fncli project-show --project "$PROJECT"
  echo "--- results repo: branches and pull requests"
  gitea_get "repos/gitea_admin/proxysim-results/branches" | jq -r '.[].name'
  gitea_get "repos/gitea_admin/proxysim-results/pulls?state=all" | jq -r '.[] | "#\(.number) \(.state) \(.head.ref) \(.title)"'
  echo "--- certificate errors in nexus-api and the Dagster code server (last 30 min)"
  { kubectl logs deployment/nexus-api -n "$NAMESPACE" --since=30m
    kubectl logs "deployment/${RELEASE_NAME}-${DAGSTER_USER_DEPLOYMENT:-dagster-fn}" -n "$NAMESPACE" --since=30m
  } 2>&1 | grep -E "$TLS_ERRORS" | tail -n 5 || echo "none"
  echo "--- what crossed the proxy (requests and TLS failures)"
  kubectl logs deployment/proxysim -n "$NS_PROXY" | grep -v -E 'client (dis)?connect|server (dis)?connect' | tail -n 40
}

down() {
  kubectl delete -f "$CONFIG_FILE" --ignore-not-found --timeout=180s || true
  kubectl delete secret proxysim-trigger-creds proxysim-results-creds -n "$OPERATOR_NAMESPACE" --ignore-not-found
  kubectl delete pod proxysim-probe -n "$NAMESPACE" --ignore-not-found
  kubectl delete secret "$CUSTOM_CA_SECRET" -n "$NAMESPACE" --ignore-not-found
  kubectl delete namespace "$NS_PROXY" --ignore-not-found
  # deploy ran: the generated.values.yaml here is this test's. Yours, if any, comes back.
  if [ -d "$SAVED" ]; then
    rm -f "$GENERATED_ENV" "$GENERATED_VALUES"
    local f
    for f in "$GENERATED_ENV" "$GENERATED_VALUES"; do
      if [ -f "${SAVED}/$(basename "$f")" ]; then mv "${SAVED}/$(basename "$f")" "$f"; fi
    done
    rmdir "$SAVED"
  fi
  echo "Removed. The release still has the proxy until \`mise run deploy\`."
}

case "$COMMAND" in
  up) up; echo "Up: ${PROXY_URL}, ${HOST} -> ${GITEA_SVC}" ;;
  probe) probe ;;
  deploy) deploy ;;
  setup) via_proxy setup ;;
  pr) via_proxy pr ;;
  status) via_proxy status ;;
  down) down ;;
  *)
    echo "Usage: $0 <up|probe|deploy none|wrong|right|setup|pr|status|down>"
    exit 1
    ;;
esac
