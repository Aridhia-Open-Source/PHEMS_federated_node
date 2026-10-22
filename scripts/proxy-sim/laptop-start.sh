#!/bin/sh
# Nested Docker defaults to MTU 1500. If the link it sits on is smaller (a VPN, WSL2), big
# packets such as a TLS handshake are dropped and every pull from a nested container times out.
mtu="$(cat /sys/class/net/eth0/mtu)"
# Extra arguments go to dockerd (scripts/sandbox.sh passes a registry mirror).
exec dind dockerd --host=unix:///var/run/docker.sock --mtu="$mtu" "$@"
