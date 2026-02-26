#!/usr/bin/env bash
set -euo pipefail


echo "Building dagster image..."
cd dagster
./build.sh
cd ../

echo "Image builds successful!"
