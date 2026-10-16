#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Dev cluster ownership - one worktree owns the shared dev cluster at a time.
# Usage: deploy_owner.sh claim|show|release
###############################################################################

CM=fn-dev-owner
NS=default

field() {
  kubectl get configmap "$CM" -n "$NS" -o jsonpath="{.data.$1}"
}

case "${1:-}" in
  claim)
    here="$(git rev-parse --show-toplevel)"
    owner="$(kubectl get configmap "$CM" -n "$NS" -o jsonpath='{.data.worktree}' --ignore-not-found)"
    if [ -n "$owner" ] && [ "$owner" != "$here" ] && [ "${FORCE_OWNER:-}" != "1" ]; then
      echo "dev cluster is owned by $(field branch) ($owner) since $(field at). Tear it down from there, or rerun with FORCE_OWNER=1 to take it over." >&2
      exit 1
    fi
    kubectl create configmap "$CM" -n "$NS" \
      --from-literal=worktree="$here" \
      --from-literal=branch="$(git branch --show-current)" \
      --from-literal=sha="$(git rev-parse --short HEAD)" \
      --from-literal=at="$(date -Iseconds)" \
      --from-literal=by="${DEPLOY_BY:-$USER}" \
      --dry-run=client -o yaml | kubectl apply -f -
    ;;
  show)
    if [ -z "$(kubectl get configmap "$CM" -n "$NS" -o name --ignore-not-found)" ]; then
      echo "dev cluster: free"
    else
      echo "dev cluster owner: $(field branch)"
      echo "  worktree: $(field worktree)"
      echo "  sha:      $(field sha)"
      echo "  at:       $(field at)"
      echo "  by:       $(field by)"
    fi
    ;;
  release)
    kubectl delete configmap "$CM" -n "$NS" --ignore-not-found
    ;;
  *)
    echo "usage: $0 claim|show|release" >&2
    exit 2
    ;;
esac
