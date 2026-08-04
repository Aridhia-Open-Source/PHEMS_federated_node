#!/bin/bash
set -euo pipefail

# UC1 Seed Script (master orchestrator)
# Drops, creates schema, seeds synthetic data, and registers in backend API

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -a
source "$SCRIPT_DIR/.env"
set +a

GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=== UC1 OMOP Database Seed ===${NC}"
echo ""

# Validate tools
for tool in psql python3; do
  if ! command -v $tool &> /dev/null; then
    echo -e "${RED}ERROR: $tool not found${NC}" >&2
    exit 1
  fi
done

# Step 1: Drop existing tables
echo -e "${BLUE}[1/3] Dropping existing UC1 tables...${NC}"
"$SCRIPT_DIR/uc1_drop.sh"

# Step 2: Generate and load schema + synthetic data
echo -e "${BLUE}[2/3] Generating and loading OMOP CDM schema + synthetic data...${NC}"
PGPASSWORD="$DATASET_PASSWORD" python3 "$SCRIPT_DIR/uc1_seed.py" "$SCRIPT_DIR/uc1_fields.csv" | \
  psql -h "$LOCAL_DATASET_HOST" -p "$LOCAL_DATASET_PORT" \
    -U "$DATASET_USERNAME" -d "$DATASET_NAME" > /dev/null

if [ $? -eq 0 ]; then
  echo -e "${GREEN}✓ OMOP CDM schema and data loaded${NC}"
else
  echo -e "${RED}ERROR: Failed to load schema/data${NC}"
  exit 1
fi
echo ""

# Step 3: Register dataset & repository in backend API
echo -e "${BLUE}[3/3] Registering dataset and repository in backend...${NC}"
cd "$SCRIPT_DIR"
python3 backend_seed.py

if [ $? -eq 0 ]; then
  echo -e "${GREEN}✓ Backend registration complete${NC}"
else
  echo -e "${RED}ERROR: Failed to register in backend${NC}"
  exit 1
fi
echo ""

echo -e "${GREEN}✓ UC1 OMOP database fully seeded!${NC}"
echo ""
echo -e "${BLUE}To verify, run: python3 uc1_read.py${NC}"
echo ""
