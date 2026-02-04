#!/usr/bin/env bash
set -euo pipefail


echo "Building dagster image..."
cd dagster
./build.sh
cd ../

echo "Building model images..."
cd docker_models
./build.sh julia
cd ../

cd docker_models
./build.sh python
cd ../

echo "Image builds successful!"
