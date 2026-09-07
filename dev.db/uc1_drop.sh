#!/bin/bash
set -euo pipefail

# UC1 Drop Script (Local - clears OMOP database before reseed)
# Drops all UC1 tables from the database

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables from .env
set -a
source "$SCRIPT_DIR/.env"
set +a
source "$SCRIPT_DIR/dataset_password.sh"

# Configuration - ALL REQUIRED, no defaults
# Each must be explicitly set as environment variable
LOCAL_DATASET_HOST="${LOCAL_DATASET_HOST}"
LOCAL_DATASET_PORT="${LOCAL_DATASET_PORT}"
DATASET_NAME="${DATASET_NAME}"
DATASET_USERNAME="${DATASET_USERNAME}"
DATASET_PASSWORD="${DATASET_PASSWORD}"
DATASET_SCHEMA="${DATASET_SCHEMA}"
DATASET_SCHEMA_WRITE="${DATASET_SCHEMA_WRITE}"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== UC1 OMOP Database Drop ===${NC}"
echo ""

# REQUIRED: Validate ALL inputs are set - no defaults, fail fast
REQUIRED_VARS=(LOCAL_DATASET_HOST LOCAL_DATASET_PORT DATASET_NAME DATASET_USERNAME DATASET_PASSWORD DATASET_SCHEMA DATASET_SCHEMA_WRITE)
for var in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!var:-}" ]; then
    echo -e "${RED}ERROR: Required environment variable '$var' is not set${NC}" >&2
    exit 1
  fi
done

# Validate required tools
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

echo -e "${BLUE}[1/1] Dropping UC1 tables...${NC}"
# uc1_seed.py creates the CDM and write schemas from scratch, so dropping the
# schemas is both sufficient and necessary -- a stale schema makes its
# "CREATE SCHEMA" fail on the next seed.
PGPASSWORD="$DATASET_PASSWORD" psql -v ON_ERROR_STOP=1 \
  -h "$LOCAL_DATASET_HOST" -p "$LOCAL_DATASET_PORT" \
  -U "$DATASET_USERNAME" -d "$DATASET_NAME" \
  -c "DROP SCHEMA IF EXISTS \"$DATASET_SCHEMA\" CASCADE;
      DROP SCHEMA IF EXISTS \"$DATASET_SCHEMA_WRITE\" CASCADE;" > /dev/null

if [ $? -eq 0 ]; then
  echo -e "${GREEN}✓ UC1 tables dropped${NC}"
else
  echo -e "${RED}ERROR: Failed to drop tables${NC}"
  exit 1
fi

echo ""
echo -e "${GREEN}✓ UC1 OMOP database cleared!${NC}"
echo ""
echo -e "${BLUE}Next step: Reseed the database${NC}"
echo ""
echo "  Run: ./seed_uc1.sh"
echo ""
