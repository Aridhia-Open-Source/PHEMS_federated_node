# Shared helpers for the m0 spike. Source this file.
export G=http://localhost:3917
export CN=gitea-spike-m0
export ORG=spike-org REPO=mirror-test
export SRC=/tmp/m0/src.git            # bare mirror clone of the public GitHub repo (no token)
export ADM=spikeadmin
api() { # api METHOD PATH [json] ; extra header via $SUDO
  local m=$1 p=$2 d=${3:-}
  local args=(-s -w '\nHTTP %{http_code}\n' -X "$m" -H "Authorization: token $TOKEN" -H 'Content-Type: application/json')
  [ -n "${SUDO:-}" ] && args+=(-H "Sudo: $SUDO")
  [ -n "$d" ] && args+=(-d "$d")
  echo ">>> $m /api/v1$p ${SUDO:+(Sudo: $SUDO)} ${d:+ $d}"
  curl "${args[@]}" "$G/api/v1$p"
}
