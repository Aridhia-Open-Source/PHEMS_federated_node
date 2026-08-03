#!/bin/bash
set -euo pipefail

# UC1 Drop Script (Local - clears OMOP database before reseed)
# Drops all UC1 tables from the database

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables from .env
set -a
source "$SCRIPT_DIR/.env"
set +a

# Configuration - ALL REQUIRED, no defaults
# Each must be explicitly set as environment variable
LOCAL_DATASET_HOST="${LOCAL_DATASET_HOST}"
LOCAL_DATASET_PORT="${LOCAL_DATASET_PORT}"
DATASET_NAME="${DATASET_NAME}"
DATASET_USERNAME="${DATASET_USERNAME}"
DATASET_PASSWORD="${DATASET_PASSWORD}"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== UC1 OMOP Database Drop ===${NC}"
echo ""

# REQUIRED: Validate ALL inputs are set - no defaults, fail fast
REQUIRED_VARS=(LOCAL_DATASET_HOST LOCAL_DATASET_PORT DATASET_NAME DATASET_USERNAME DATASET_PASSWORD)
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
echo ""

echo -e "${BLUE}[1/1] Dropping UC1 tables...${NC}"
PGPASSWORD="$DATASET_PASSWORD" psql -h "$LOCAL_DATASET_HOST" -p "$LOCAL_DATASET_PORT" \
  -U "$DATASET_USERNAME" -d "$DATASET_NAME" \
  -c "DROP TABLE IF EXISTS death CASCADE;
      DROP TABLE IF EXISTS condition_occurrence CASCADE;
      DROP TABLE IF EXISTS procedure_occurrence CASCADE;
      DROP TABLE IF EXISTS visit_detail CASCADE;
      DROP TABLE IF EXISTS visit_occurrence CASCADE;
      DROP TABLE IF EXISTS observation_period CASCADE;
      DROP TABLE IF EXISTS person CASCADE;
      DROP TABLE IF EXISTS concept_ancestor CASCADE;
      DROP TABLE IF EXISTS concept CASCADE;
      DROP TABLE IF EXISTS cdm_source CASCADE;
      DROP TABLE IF EXISTS domain CASCADE;
      DROP TABLE IF EXISTS vocabulary CASCADE;
      DROP SCHEMA IF EXISTS write_schema CASCADE;" > /dev/null 2>&1

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
