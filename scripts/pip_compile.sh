#!/usr/bin/env bash
set -euo pipefail

# usage ./pip_compile.sh {dir} [output-file] --{opt1} --{opt2}
# --generate-hashes                 generate hashes for security
# --no-header                       disable requirements file argument header
# --no-emit-options                 disable requirements file options header
# --no-emit-trusted-host            prevent leaking trusted host url
# --no-emit-index-url               prevent leaking index url basic auth
# --resolver=backtracking           use the new improved resolver
# --strip-extras                    strip extras for pip compatibility
# --allow-unsafe                    this is safe (misleading), allows pinning of standard tools
# --verbose                         print debug information
# --output-file=requirements.txt    specify the output file name

DIR="${1:-.}"
shift || true
OUTPUT_FILE="requirements.txt"
if [[ -n "${1:-}" && "${1}" != --* ]]; then
    OUTPUT_FILE="${1}"
    shift
fi
pushd "$DIR" > /dev/null

# The component's own Python (its mise.toml), which `mise run setup` gives pip-tools
if ! mise exec -- python -m piptools --help > /dev/null 2>&1; then
    echo "Error: pip-tools is not installed for ${DIR}. Run \`mise run setup\` first." >&2
    exit 1
fi

mise exec -- python -m piptools compile \
    --generate-hashes \
    --no-header \
    --no-emit-options \
    --no-emit-trusted-host \
    --no-emit-index-url \
    --resolver=backtracking \
    --strip-extras \
    --allow-unsafe \
    --verbose \
    --output-file="$OUTPUT_FILE" \
    "$@" \
    pyproject.toml

