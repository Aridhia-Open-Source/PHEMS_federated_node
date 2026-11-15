# shellcheck shell=bash
# Sourced by deploy.sh and configure.sh. Dev tooling for the chart's customCA value.
#
# CUSTOM_CA_FILE=/path/to/ca.pem (.generated.env or .dev.env) puts that PEM, a CA or a bundle
# of them, in the Secret CUSTOM_CA_SECRET in $NAMESPACE. The release trusts it for outbound
# TLS once customCA.secretName names that Secret, which configure.sh --ca-cert or --proxy
# writes in generated.values.yaml. Unset, nothing is created.
CUSTOM_CA_SECRET=fn-custom-ca-dev

custom_ca_prepare() {
  [ -n "${CUSTOM_CA_FILE:-}" ] || return 0
  [ -s "$CUSTOM_CA_FILE" ] || { echo "CUSTOM_CA_FILE=$CUSTOM_CA_FILE is missing or empty" >&2; return 1; }
  grep -q -e '-----BEGIN CERTIFICATE-----' "$CUSTOM_CA_FILE" \
    || { echo "CUSTOM_CA_FILE=$CUSTOM_CA_FILE holds no PEM certificate" >&2; return 1; }
  echo "Custom CA: $CUSTOM_CA_FILE -> secret $CUSTOM_CA_SECRET in $NAMESPACE"
  kubectl create secret generic "$CUSTOM_CA_SECRET" --from-file=ca.crt="$CUSTOM_CA_FILE" \
    --dry-run=client -o yaml -n "$NAMESPACE" | kubectl apply -f - -n "$NAMESPACE"
}
