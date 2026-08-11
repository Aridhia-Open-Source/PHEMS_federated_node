#!/bin/bash
set -euo pipefail

# UC3 Drop Script (Local - clears the haemophilia OMOP database before reseed)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables from uc3.env
set -a
source "$SCRIPT_DIR/uc3.env"
set +a
source "$SCRIPT_DIR/dataset_password.sh"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== UC3 OMOP Database Drop ===${NC}"
echo ""

# REQUIRED: Validate ALL inputs are set - no defaults, fail fast
REQUIRED_VARS=(LOCAL_DATASET_HOST LOCAL_DATASET_PORT DATASET_NAME DATASET_USERNAME DATASET_PASSWORD DATASET_SCHEMA DATASET_SCHEMA_WRITE)
for var in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!var:-}" ]; then
    echo -e "${RED}ERROR: Required environment variable '$var' is not set${NC}" >&2
    exit 1
  fi
done

if ! command -v psql &> /dev/null; then
  echo -e "${RED}ERROR: psql not found. Install PostgreSQL client tools.${NC}"
  exit 1
fi

echo -e "${BLUE}Configuration:${NC}"
echo "  LOCAL_DATASET_HOST: $LOCAL_DATASET_HOST"
echo "  LOCAL_DATASET_PORT: $LOCAL_DATASET_PORT"
echo "  DATASET_NAME: $DATASET_NAME"
echo "  DATASET_USERNAME: $DATASET_USERNAME"
echo "  SCHEMAS: $DATASET_SCHEMA, $DATASET_SCHEMA_WRITE"
echo ""

echo -e "${BLUE}[1/1] Dropping UC3 schemas...${NC}"
# uc3_seed.py creates the CDM and write schemas from scratch, so dropping the
# schemas is both sufficient and necessary -- a stale schema makes its
# "CREATE SCHEMA" fail on the next seed. The write schema also holds the tables
# the R stage computes (uc3_cohort, uc3_measurements, uc3_treatment), which must
# not survive a reseed of the data underneath them.
PGPASSWORD="$DATASET_PASSWORD" psql -v ON_ERROR_STOP=1 \
  -h "$LOCAL_DATASET_HOST" -p "$LOCAL_DATASET_PORT" \
  -U "$DATASET_USERNAME" -d "$DATASET_NAME" \
  -c "DROP SCHEMA IF EXISTS \"$DATASET_SCHEMA\" CASCADE;
      DROP SCHEMA IF EXISTS \"$DATASET_SCHEMA_WRITE\" CASCADE;" > /dev/null

echo -e "${GREEN}✓ UC3 OMOP database cleared!${NC}"
echo ""
