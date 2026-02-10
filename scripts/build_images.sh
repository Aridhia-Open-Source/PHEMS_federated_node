#!/usr/bin/env bash
set -euo pipefail


echo "Building dagster image..."
cd dagster
./build.sh
cd ../

echo "Building julia model image..."
cd docker_models
./build.sh julia
cd ../

echo "Building python model image..."
cd docker_models
./build.sh python
cd ../

echo "Building webserver image..."
cd webserver
./build.sh
cd ../

echo "Image builds successful!"
