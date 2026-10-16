import pytest
from sqlalchemy.orm.session import close_all_sessions
from alembic.config import Config
from alembic import command

from app import create_app
from app.helpers.base_model import db, engine


@pytest.fixture(scope='session', autouse=True)
def check_database_connection():
    """Check database connectivity before running any tests."""
    from sqlalchemy import text
    import time
    max_retries = 5
    retry_delay = 1
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"DB connection attempt {attempt + 1}/{max_retries} failed, retrying...")
                time.sleep(retry_delay)
            else:
                msg = f"DATABASE UNAVAILABLE: Could not connect after {max_retries} attempts: {e}"
                print(f"\n{msg}\n")
                pytest.exit(msg, 1)


@pytest.fixture
def client():
    app = create_app()
    app.testing = True
    with app.test_client() as tclient:
        with app.app_context():
            yield tclient
            close_all_sessions()
