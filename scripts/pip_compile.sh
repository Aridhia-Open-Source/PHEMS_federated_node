#!/usr/bin/env bash
set -euo pipefail

# usage ./compile.sh {dir} [output-file] --{opt1} --{opt2}
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

if ! command -v pip-compile > /dev/null 2>&1; then
    echo "Error: pip-compile is required to generate requirements.txt." >&2
    echo "Install the pip-tools package first, for example:" >&2
    echo "  python -m pip install pip-tools" >&2
    exit 1
fi

pip-compile \
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

