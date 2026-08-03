#!/bin/bash
set -euo pipefail

# UC1 Seed Script (Local - for seeding OMOP database after k8s deployment)
# Creates OMOP schema and seeds with synthetic data
#
# NOTE: This script seeds the EXPERIMENT DATABASE ONLY
# Backend API registration (Dataset + Repository) must be done separately
# after deployment via: cd dbseed && python3 seed_backend.py

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
NUM_PATIENTS="${NUM_PATIENTS:-100}"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== UC1 OMOP Database Seeding ===${NC}"
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

if ! command -v python3 &> /dev/null; then
  echo -e "${RED}ERROR: python3 not found. Install Python 3.${NC}"
  exit 1
fi

echo -e "${BLUE}Configuration:${NC}"
echo "  LOCAL_DATASET_HOST: $LOCAL_DATASET_HOST"
echo "  LOCAL_DATASET_PORT: $LOCAL_DATASET_PORT"
echo "  DATASET_NAME: $DATASET_NAME"
echo "  DATASET_USERNAME: $DATASET_USERNAME"
echo "  NUM_PATIENTS: $NUM_PATIENTS"
echo ""

# Step 1: Create OMOP schema
echo -e "${BLUE}[1/2] Creating OMOP schema...${NC}"
PGPASSWORD="$DATASET_PASSWORD" psql -h "$LOCAL_DATASET_HOST" -p "$LOCAL_DATASET_PORT" \
  -U "$DATASET_USERNAME" -d "$DATASET_NAME" \
  -f "$SCRIPT_DIR/seed_uc1_schema.sql" > /dev/null 2>&1

if [ $? -eq 0 ]; then
  echo -e "${GREEN}✓ Schema created${NC}"
else
  echo "WARNING: Schema creation completed (may have had expected conflicts)"
fi

# Step 2: Seed synthetic data
echo -e "${BLUE}[2/2] Seeding synthetic data (${NUM_PATIENTS} patients)...${NC}"
python3 "$SCRIPT_DIR/seed_uc1_data.py" \
  --host "$LOCAL_DATASET_HOST" \
  --port "$LOCAL_DATASET_PORT" \
  --user "$DATASET_USERNAME" \
  --password "$DATASET_PASSWORD" \
  --dbname "$DATASET_NAME" \
  --num-patients "$NUM_PATIENTS"

if [ $? -ne 0 ]; then
  echo -e "${RED}ERROR: Data seeding failed${NC}"
  exit 1
fi

echo ""
echo -e "${GREEN}✓ UC1 OMOP database seeded successfully!${NC}"
echo ""
echo -e "${BLUE}Next step: Register Dataset and Repository in backend API${NC}"
echo ""
echo "  Run: python3 seed_backend.py"
echo ""
