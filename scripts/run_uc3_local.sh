#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Run the UC3 analysis image (uc3-dose-interference-model) on this machine,
# against the dev cluster's dataset DB, without going through Dagster or the
# task API.
#
# Reproduces exactly the contract dagster/app/definitions/pipes.py gives a task
# pod:
#   CONNECTION_STRING  server=...;database=...;port=...;uid=...;pwd=...;
#   CDM_SCHEMA         read schema
#   WRITE_SCHEMA       write schema (the R stage computes its tables here)
#   ARTIFACT_PATH      where results are written
#
# Requires ./scripts/portfwd.sh (or tilt) for the db-datasets forward on 5433.
#
# Usage: ./scripts/run_uc3_local.sh [tag]        (default tag: latest)
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
TAG="${1:-latest}"
IMAGE="${IMAGE:-localhost:5001/uc3-fn:${TAG}}"

set -a
source "$ROOT_DIR/dev.db/uc3.env"
set +a
source "$ROOT_DIR/dev.db/dataset_password.sh"

OUT_DIR="${OUT_DIR:-$ROOT_DIR/uc3-local-results}"
mkdir -p "$OUT_DIR"
# The image runs as its own `app` user, whose uid does not match the host user
# owning this directory, so a bind mount alone leaves it unwritable. In the cluster
# the run pod creates the artifact directory for the task pod instead
# (_prepare_artifact_dir in dagster/app/definitions/pipes.py).
chmod 0777 "$OUT_DIR"

# The container talks to the port-forward on the host, so --network host. That
# also means LOCAL_DATASET_HOST/PORT are the right coordinates, not the
# in-cluster ones the dataset row carries.
CONNECTION_STRING="server=${LOCAL_DATASET_HOST};database=${DATASET_NAME};port=${LOCAL_DATASET_PORT};uid=${DATASET_USERNAME};pwd=${DATASET_PASSWORD};"

echo "Image:     $IMAGE"
echo "Database:  ${LOCAL_DATASET_HOST}:${LOCAL_DATASET_PORT}/${DATASET_NAME}"
echo "Schemas:   read=${DATASET_SCHEMA} write=${DATASET_SCHEMA_WRITE}"
echo "Results:   $OUT_DIR"
echo

if ! PGPASSWORD="$DATASET_PASSWORD" psql -h "$LOCAL_DATASET_HOST" -p "$LOCAL_DATASET_PORT" \
     -U "$DATASET_USERNAME" -d "$DATASET_NAME" -c 'select 1' > /dev/null 2>&1; then
  echo "ERROR: cannot reach ${LOCAL_DATASET_HOST}:${LOCAL_DATASET_PORT} - is the port-forward up?" >&2
  echo "       run ./scripts/portfwd.sh, or start tilt" >&2
  exit 1
fi

# The task pod runs as an arbitrary uid with the artifact directory pre-created by
# the run pod; mirror that here so a permissions problem shows up locally too.
exec docker run --rm \
  --network host \
  -e CONNECTION_STRING="$CONNECTION_STRING" \
  -e CDM_SCHEMA="$DATASET_SCHEMA" \
  -e WRITE_SCHEMA="$DATASET_SCHEMA_WRITE" \
  -e ARTIFACT_PATH=/artifacts \
  -v "$OUT_DIR:/artifacts" \
  "$IMAGE"
