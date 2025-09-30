#!/bin/bash

full_image=${1:-"ghcr.io/aridhia-open-source/federated_node_run:0.0.1"}
archive_name="fn.tar"

docker save "$full_image" > "$archive_name"
microk8s ctr image import "$archive_name"
rm "$archive_name"
