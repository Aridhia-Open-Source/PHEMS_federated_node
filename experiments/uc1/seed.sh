#!/usr/bin/env bash
# Prints the SQL that seeds UC1's database: the OMOP CDM 5.4 schema plus synthetic data.
# It drops and recreates its own schemas, so it is safe to re-run.
set -euo pipefail
SEED_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/seed"
python3 "$SEED_DIR/uc1_seed.py" "$SEED_DIR/uc1_fields.csv"
