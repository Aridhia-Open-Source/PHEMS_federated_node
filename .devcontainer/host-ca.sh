#!/bin/sh
# Runs on the host before the dev container is created (initializeCommand). Copies the proxy CA
# that scripts/setup-proxy-ca.sh set up (CUSTOM_CA_FILE in .dev.env) to ~/.fn/proxy-ca.crt, which
# devcontainer.json mounts read-only. With no CA the copy is an empty file: a bind mount needs its
# source to exist, and postCreateCommand skips an empty file.
set -eu
cd "$(dirname "$0")/.."
mkdir -p "$HOME/.fn/data"
ca="$(sed -n 's/^\(export \)\{0,1\}CUSTOM_CA_FILE=//p' .dev.env 2> /dev/null | tail -n 1 | tr -d "\"'")"
if [ -n "$ca" ] && [ -s "$ca" ]; then
  cp -f "$ca" "$HOME/.fn/proxy-ca.crt"
else
  : > "$HOME/.fn/proxy-ca.crt"
fi
