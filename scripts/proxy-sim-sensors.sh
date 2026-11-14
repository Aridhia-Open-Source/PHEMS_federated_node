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
# Three runs, each a deploy of the release with the proxy set and one cert mode:
#   none    no customCA                  expected: the pipeline fails with a TLS/certificate error
#   wrong   customCA = an unrelated CA   expected: the same
#   right   customCA = mitmproxy's CA    expected: the merged PR is ingested, the task runs and the
#                                        results branch and results PR appear in Gitea
#
#   ./scripts/proxy-sim-sensors.sh up                   # mitmproxy in the proxysim namespace (keeps its CA)
#   ./scripts/proxy-sim-sensors.sh probe                # curl through the proxy: fails without the CA, works with it
#   ./scripts/proxy-sim-sensors.sh deploy <none|wrong|right>
#                                                       # scripts/deploy.sh with DEV_PROXY_URL and that CA
#   ./scripts/proxy-sim-sensors.sh setup                # the proxysim project, its Gitea repos and secrets (fncli)
#   ./scripts/proxy-sim-sensors.sh pr                   # open and merge one watched PR in the trigger repo
#   ./scripts/proxy-sim-sensors.sh status               # the project, TLS errors in the logs, what crossed the proxy
#   ./scripts/proxy-sim-sensors.sh down                 # remove the project, its repos, proxysim and the CA secret
#
# Needs the port-forwards (mise run portfwd; not Tilt, which deploys without the proxy) and
# dagster/.venv (mise run setup), or FNCLI_PYTHON set to a python that runs fncli. The CAs and
# fncli's env file are kept in $PROXYSIM_DIR (default ~/.fn/proxysim-sensors). After `down`,
# `mise run deploy` puts the release back without the proxy.
####################################################################################

cd "$(dirname "$0")/.."
ROOT="$PWD"

COMMAND="${1:-}"
MODE="${2:-}"

source .dev.env
NS_PROXY="proxysim"
DIR="${PROXYSIM_DIR:-$HOME/.fn/proxysim-sensors}"
IMAGE="${PROXYSIM_IMAGE:-mitmproxy/mitmproxy:latest}"
CLUSTER="${CLUSTER_NAME:-fn}"
PROXY_URL="http://proxysim.${NS_PROXY}.svc:8080"
HOST="gitea.proxysim.test"
GITEA_SVC="http://gitea.${NAMESPACE}.svc:4000"
FNCLI_PYTHON="${FNCLI_PYTHON:-$ROOT/dagster/.venv/bin/python}"
ENV_FILE="${DIR}/fncli.env"
# What a client prints when it does not trust the certificate it was shown.
TLS_ERRORS='x509:|certificate verify failed|CERTIFICATE_VERIFY_FAILED|SSL certificate problem|unknown authority|SSLError'

mkdir -p "$DIR"

# Without .dev.env's PYTHONPATH=./app, whose secrets.py hides the standard library's.
fncli() { (cd "$ROOT/dagster" && env -u PYTHONPATH "$FNCLI_PYTHON" -m fncli --env-file "$ENV_FILE" "$@"); }

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
  DEV_PROXY_URL="$PROXY_URL" CUSTOM_CA_FILE="$ca" ./scripts/deploy.sh
}

# fncli's settings for the test project: its own names, so it never touches the dev project,
# and the repositories under the outside name, so the node reaches them through the proxy.
write_env() {
  cat > "$ENV_FILE" <<EOF
KEYCLOAK_NAMESPACE=keycloak
NEXUS_API_URL=http://localhost:5000
GITEA_URL=http://localhost:4000
GITEA_API_URI=https://${HOST}/api/v1
TEST_PROJECT_NAME=proxysim
TEST_TRIGGER_REPO=proxysim-trigger
TEST_TRIGGER_REPO_URI=https://${HOST}/gitea_admin/proxysim-trigger
TEST_TRIGGER_REPO_WATCH_DIR=specs/
TEST_TRIGGER_REPO_BASE_BRANCH=main
TEST_RESULTS_REPO=proxysim-results
TEST_RESULTS_REPO_URI=https://${HOST}/gitea_admin/proxysim-results
TEST_RESULTS_TARGET_DIR=results/
TEST_RESULTS_REPO_BASE_BRANCH=main
DEFAULT_PROJECT_DATASET=proxysim-dataset
GITEA_TOKEN_NAME=proxysim-trigger
GITEA_RESULTS_TOKEN_NAME=proxysim-results
TEST_PR_IMAGE=localhost:5001/pypipes-fn:latest
EOF
}

# setup-project minus verify-git-secret, which calls the provider from this host: it cannot
# resolve the outside name.
setup() {
  write_env
  fncli init-backend-project
  fncli init-gitea-repo --entity trigger
  fncli init-gitea-repo --entity results
  fncli init-git-secret --entity trigger
  fncli init-git-secret --entity results
  fncli init-dataset-secret
  fncli init-backend-trigger-repo
  fncli init-backend-results-repo
  fncli init-backend-dataset
  fncli project-set --enabled true
}

gitea_get() {
  local password
  password="$(kubectl get secret gitea-admin -n "$NAMESPACE" -o jsonpath='{.data.password}' | base64 -d)"
  curl -sS --fail -u "gitea_admin:${password}" "http://localhost:4000/api/v1/$1"
}

status() {
  echo "--- the project's pull requests, tasks and results"
  fncli project-show | jq '{pull_requests: [.pull_requests[]? | {number, status, task_id}],
    tasks: [.tasks[]? | {id, status}], results: [.results[]? | {task_id, step, status, number}]}' 2>/dev/null \
    || fncli project-show
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
  [ -f "$ENV_FILE" ] && fncli teardown-project -y || true
  kubectl delete pod proxysim-probe -n "$NAMESPACE" --ignore-not-found
  kubectl delete secret fn-custom-ca-dev -n "$NAMESPACE" --ignore-not-found
  kubectl delete namespace "$NS_PROXY" --ignore-not-found
  echo "Removed. The release still has the proxy until \`mise run deploy\` without DEV_PROXY_URL."
}

case "$COMMAND" in
  up) up; echo "Up: ${PROXY_URL}, ${HOST} -> ${GITEA_SVC}" ;;
  probe) probe ;;
  deploy) deploy ;;
  setup) setup ;;
  pr) write_env; fncli open-pr --merge ;;
  status) status ;;
  down) down ;;
  *)
    echo "Usage: $0 <up|probe|deploy none|wrong|right|setup|pr|status|down>"
    exit 1
    ;;
esac
