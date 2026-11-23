"""One test database per pytest-xdist worker, so parallel workers don't share state.

The app builds its engine from NEXUS_DB_NAME when `app` is first imported, and tests/conftest.py imports it,
so the name is set here: pytest loads this conftest first, and it imports nothing from `app`. It is set in
os.environ so the alembic subprocesses in test_migrations.py use it too. A serial run (-n 0) keeps the name.
"""
import os

from sqlalchemy import create_engine, text

worker = os.environ.get("PYTEST_XDIST_WORKER")
if worker:
    db_name = f"{os.environ['NEXUS_DB_NAME']}_{worker}"
    os.environ["NEXUS_DB_NAME"] = db_name
    admin_uri = (
        f"postgresql://{os.environ['NEXUS_DB_USER']}:{os.environ['NEXUS_DB_PASSWORD']}"
        f"@{os.environ['PGHOST']}:{os.environ['PGPORT']}/postgres"
    )
    admin_engine = create_engine(admin_uri, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}).scalar():
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()
