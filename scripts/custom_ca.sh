# Sourced by deploy.sh and upgrade.sh. Dev tooling for the chart's customCA value.
#
# CUSTOM_CA_FILE=/path/to/ca.pem (set it in .dev.env) puts that PEM, a CA or a bundle of
# them, in a Secret in $NAMESPACE and fills CUSTOM_CA_HELM_ARGS with the Helm arguments
# that make the release trust it for outbound TLS. Unset, CUSTOM_CA_HELM_ARGS stays empty
# and nothing is created. Certificates are always verified.
CUSTOM_CA_SECRET=fn-custom-ca-dev

custom_ca_prepare() {
  CUSTOM_CA_HELM_ARGS=()
  [ -n "${CUSTOM_CA_FILE:-}" ] || return 0
  [ -s "$CUSTOM_CA_FILE" ] || { echo "CUSTOM_CA_FILE=$CUSTOM_CA_FILE is missing or empty" >&2; return 1; }
  grep -q -e '-----BEGIN CERTIFICATE-----' "$CUSTOM_CA_FILE" \
    || { echo "CUSTOM_CA_FILE=$CUSTOM_CA_FILE holds no PEM certificate" >&2; return 1; }
  echo "Custom CA: $CUSTOM_CA_FILE -> secret $CUSTOM_CA_SECRET in $NAMESPACE"
  kubectl create secret generic "$CUSTOM_CA_SECRET" --from-file=ca.crt="$CUSTOM_CA_FILE" \
    --dry-run=client -o yaml -n "$NAMESPACE" | kubectl apply -f - -n "$NAMESPACE"
  CUSTOM_CA_HELM_ARGS=(--set "customCA.secretName=$CUSTOM_CA_SECRET" --set "customCA.key=ca.crt")
}
