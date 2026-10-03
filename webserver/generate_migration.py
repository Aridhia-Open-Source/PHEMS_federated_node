#!/usr/bin/env python3
"""
Generate baseline migration from current models.
Run this when alembic CLI is available: python generate_migration.py
"""
import sys
import os
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

if __name__ == '__main__':
    try:
        from sqlalchemy import inspect
        from app.helpers.base_model import Base, db
        import app.models.dataset
        import app.models.project
        import app.models.pull_request
        import app.models.trigger
        import app.models.task
        import app.models.task_status
        import app.models.trigger_repository
        import app.models.results_repository
        import app.models.results_backend
        import app.models.api_request

        print("✓ All models imported successfully")
        print(f"✓ {len(Base.metadata.tables)} tables in schema")
        print("\nTables:")
        for table_name in sorted(Base.metadata.tables.keys()):
            print(f"  - {table_name}")

        print("\nTo generate the migration, run:")
        print("  cd webserver")
        print("  alembic revision --autogenerate -m 'baseline'")
        print("\nThen review migrations/versions/XXX_baseline.py before applying.")

    except Exception as e:
        print(f"✗ Error: {e}")
        sys.exit(1)
