#!/bin/sh
# Runs on the host before the dev container is built (initializeCommand). Copies the proxy CA
# that scripts/setup-proxy-ca.sh set up (CUSTOM_CA_FILE in .dev.env) to .devcontainer/proxy-ca.crt
# (gitignored), which the Dockerfile adds to the image's system trust. With no CA the copy is an
# empty file: the Dockerfile's COPY needs it to exist, and skips an empty one.
# Also creates ~/.fn/data: a bind mount fails when its source is missing.
set -eu
cd "$(dirname "$0")/.."
mkdir -p "$HOME/.fn/data"
ca="$(sed -n 's/^\(export \)\{0,1\}CUSTOM_CA_FILE=//p' .dev.env 2> /dev/null | tail -n 1 | tr -d "\"'")"
if [ -n "$ca" ] && [ -s "$ca" ]; then
  cp -f "$ca" .devcontainer/proxy-ca.crt
else
  : > .devcontainer/proxy-ca.crt
fi
