#!/bin/bash
# The API contract fixtures are written by webserver/tests/test_api_contract.py to
# webserver/tests/contracts/. Dagster's test image is built from dagster/ alone, so it gets a copy
# in dagster/app/tests/contracts/. fncli reads the webserver files directly.
#
#   scripts/sync_contract_fixtures.sh          copy them
#   scripts/sync_contract_fixtures.sh --check  fail if the copy is out of date
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
source_dir="$root/webserver/tests/contracts"
target_dir="$root/dagster/app/tests/contracts"

if [[ "${1:-}" == "--check" ]]; then
    diff -r "$source_dir" "$target_dir" && echo "Contract fixtures are in sync"
else
    rm -rf "$target_dir"
    mkdir -p "$target_dir"
    cp "$source_dir"/*.json "$target_dir"/
    echo "Copied $(ls "$target_dir" | wc -l) fixtures to $target_dir"
fi
