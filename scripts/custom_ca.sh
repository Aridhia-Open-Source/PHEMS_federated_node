# shellcheck shell=bash
# Sourced by deploy.sh. Dev tooling for the chart's customCA value.
#
# CUSTOM_CA_FILE=/path/to/ca.pem (.generated.env or .dev.env, written by configure.sh --ca-cert
# or --proxy) is a CA, or a bundle of them, the release trusts for outbound TLS. It goes to the
# chart as customCA.pem, which renders the Secret in every namespace that mounts it. Unset,
# CUSTOM_CA_ARGS is empty.
CUSTOM_CA_ARGS=()

custom_ca_prepare() {
  [ -n "${CUSTOM_CA_FILE:-}" ] || return 0
  [ -s "$CUSTOM_CA_FILE" ] || { echo "CUSTOM_CA_FILE=$CUSTOM_CA_FILE is missing or empty" >&2; return 1; }
  grep -q -e '-----BEGIN CERTIFICATE-----' "$CUSTOM_CA_FILE" \
    || { echo "CUSTOM_CA_FILE=$CUSTOM_CA_FILE holds no PEM certificate" >&2; return 1; }
  echo "Custom CA: $CUSTOM_CA_FILE -> customCA.pem"
  CUSTOM_CA_ARGS=(--set-file "customCA.pem=$(realpath "$CUSTOM_CA_FILE")")
}
