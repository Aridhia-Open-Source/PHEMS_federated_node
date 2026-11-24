#!/usr/bin/env bash
# Validates a site repository (ADR 0031) before its pull request merges. Run from the repository root.
#   1. kustomize build: what Flux applies builds, and so does each secrets/ option (sops, vault), listed or not.
#   2. helm template: the pinned chart renders with the site's values, which also checks them against the
#      chart's values schema. The chart comes from the HelmRepository url and the HelmRelease version.
#   3. SOPS: every file .sops.yaml says to encrypt is encrypted, and its data/stringData values are too; and so
#      is every Secret the kustomize build outputs, whatever its file is called.
# Needs helm, kustomize and yq (ci/install-tools.sh). No cluster, no keys and no cloud credentials.
#
# Overrides:
#   CHART_PATH=<dir>  render a local chart directory instead of pulling the pinned one
#   SKIP_SOPS=1       skip step 3 (the FN repository's own check of site-example, whose secret is a placeholder)
set -euo pipefail

HELMRELEASE="${HELMRELEASE:-helmrelease.yaml}"
HELMREPOSITORY="${HELMREPOSITORY:-helmrepository.yaml}"
VALUES="${VALUES:-values.yaml}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "== kustomize build"
kustomize build . > "$TMP/built.yaml"
echo "ok: $(yq ea '[.kind] | length' "$TMP/built.yaml") objects"
for dir in secrets/*/; do
  kustomize build "$dir" > /dev/null
  echo "ok: $dir"
done

echo "== helm template"
if [ -n "${CHART_PATH:-}" ]; then
  # charts/ is gitignored in the FN repository; build it when missing
  [ -d "$CHART_PATH/charts" ] || { helm dependency build "$CHART_PATH" || helm dependency update "$CHART_PATH"; } > /dev/null
  CHART="$CHART_PATH"
  VERSION_ARGS=()
else
  repo_url="$(yq '.spec.url' "$HELMREPOSITORY")"
  chart_name="$(yq '.spec.chart.spec.chart' "$HELMRELEASE")"
  chart_version="$(yq '.spec.chart.spec.version' "$HELMRELEASE")"
  CHART="${repo_url%/}/$chart_name"
  VERSION_ARGS=(--version "$chart_version")
  if [ "$(yq '.spec.insecure // false' "$HELMREPOSITORY")" = "true" ]; then
    VERSION_ARGS+=(--plain-http)
  fi
fi

# The values Flux merges, in its order: inline spec.values, then each valuesFrom entry. A Secret entry with
# a targetPath is a SOPS file CI cannot decrypt, so it gets a placeholder at that path.
yq '.spec.values // {}' "$HELMRELEASE" > "$TMP/inline-values.yaml"
VALUE_ARGS=(-f "$TMP/inline-values.yaml" -f "$VALUES")
while IFS=$'\t' read -r kind target; do
  if [ "$kind" = "Secret" ] && [ -n "$target" ] && [ "$target" != "null" ]; then
    VALUE_ARGS+=(--set-string "$target=ci-placeholder@example.invalid")
  fi
done < <(yq '(.spec.valuesFrom // [])[] | [.kind, .targetPath] | @tsv' "$HELMRELEASE")

release="$(yq '.spec.releaseName // .metadata.name' "$HELMRELEASE")"
namespace="$(yq '.spec.targetNamespace // .metadata.namespace' "$HELMRELEASE")"
helm template "$release" "$CHART" "${VERSION_ARGS[@]}" -n "$namespace" "${VALUE_ARGS[@]}" > "$TMP/rendered.yaml"
echo "ok: $CHART ${VERSION_ARGS[*]}"

if [ -n "${SKIP_SOPS:-}" ]; then
  echo "== sops: skipped (SKIP_SOPS)"
  exit 0
fi

echo "== sops"
failed=0
checked=0
while IFS= read -r regex; do
  [ -n "$regex" ] || continue
  while IFS= read -r file; do
    file="${file#./}"
    [[ "$file" =~ $regex ]] || continue
    checked=$((checked + 1))
    if [ "$(yq ea '[select(.sops.mac == null)] | length' "$file")" != "0" ]; then
      echo "NOT ENCRYPTED: $file has no sops metadata (sops encrypt -i $file)"
      failed=1
    elif [ "$(yq ea '[(.data // {}, .stringData // {}) | .[] | select(test("^ENC\[") | not)] | length' "$file")" != "0" ]; then
      echo "NOT ENCRYPTED: $file has plain data or stringData values"
      failed=1
    fi
  done < <(find . -path ./.git -prune -o -type f \( -name '*.yaml' -o -name '*.yml' \) -print)
done < <(yq '.creation_rules[].path_regex' .sops.yaml)

# A Secret in a file .sops.yaml does not match would reach the repository in plain text: check the build output
plain="$(yq ea '[select(.kind == "Secret") | select(.sops.mac == null or ([(.data // {}, .stringData // {}) | .[] | select(test("^ENC\[") | not)] | length) != 0) | .metadata.name] | join(", ")' "$TMP/built.yaml")"
if [ -n "$plain" ]; then
  echo "NOT ENCRYPTED: Secret(s) in the kustomize build with plain or no sops values: $plain (sops encrypt -i the file, and name it so .sops.yaml matches)"
  failed=1
fi
[ "$failed" = "0" ] || exit 1
echo "ok: $checked encrypted file(s), every built Secret encrypted"
