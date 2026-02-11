#!/usr/bin/env bash
set -euo pipefail

# usage ./compile.sh {dir} --{opt1} --{opt2}
# --generate-hashes                 generate hashes for security
# --no-header                       disable requirements file argument header
# --no-emit-options                 disable requirements file options header
# --no-emit-trusted-host            prevent leaking trusted host url
# --no-emit-index-url               prevent leaking index url basic auth
# --resolver=backtracking           use the new improved resolver
# --strip-extras                    strip extras for pip compatibility
# --allow-unsafe                    this is safe (misleading), allows pinning of standard tools
# --verbose                         print debug information
# --output-file=requirements.txt    specify theoutput file name

DIR="${1:-.}"
shift || true
pushd "$DIR" > /dev/null

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
    --output-file=requirements.txt \
    $@
