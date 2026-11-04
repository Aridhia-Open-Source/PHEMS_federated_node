"""The migrations build the schema the models describe.

Alembic runs as the db-migrations init container runs it (python -m alembic, from the directory
holding alembic.ini), in a subprocess so env.py's logging config doesn't touch the test process.
Both tests start from an empty database.
"""
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

import app.models  # noqa: F401  registers every model on Base.metadata
from app.helpers.base_model import Base, engine

API_DIR = Path(__file__).resolve().parents[1]


def alembic(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=API_DIR, capture_output=True, text=True
    )
    assert result.returncode == 0, f"alembic {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}"
    return result.stdout + result.stderr


def drop_everything() -> None:
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.fixture
def empty_database():
    drop_everything()
    yield
    drop_everything()


def table_names() -> set[str]:
    return set(inspect(engine).get_table_names())


def enum_names() -> set[str]:
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(text("SELECT typname FROM pg_type WHERE typtype = 'e'"))}


def test_upgrade_head_matches_the_models(empty_database):
    alembic("upgrade", "head")
    assert table_names() == set(Base.metadata.tables) | {"alembic_version"}
    # Exits non-zero if the models differ from what the migrations built
    alembic("check")


def test_downgrade_base_leaves_nothing(empty_database):
    alembic("upgrade", "head")
    alembic("downgrade", "base")
    assert table_names() == {"alembic_version"}
    assert enum_names() == set()
