import os
import pytest
from sqlalchemy.orm.session import close_all_sessions
from alembic.config import Config
from alembic import command

os.environ['GITEA_MIRROR_API_TOKEN'] = 'test-token'

from app import create_app
from app.clients import UserSyncError
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


@pytest.fixture(scope='session', autouse=True)
def migrated(check_database_connection):
    command.upgrade(Config('alembic.ini'), 'head')


class FakeGithub:
    def __init__(self):
        self.logins = ['alice', 'bob', 'alice']
        self.error = None
        self.calls = []

    def list_users(self, upstream_uri, secret_namespace, secret_key):
        self.calls.append((upstream_uri, secret_namespace, secret_key))
        if self.error:
            raise UserSyncError(self.error)
        return self.logins


class FakeGitea:
    def __init__(self):
        self.users = {'bob'}

    def ensure_user(self, login):
        if login in self.users:
            return False
        self.users.add(login)
        return True


@pytest.fixture
def github():
    return FakeGithub()


@pytest.fixture
def gitea():
    return FakeGitea()


@pytest.fixture
def client(migrated, github, gitea):
    from sqlalchemy import text
    with engine.begin() as conn:
        conn.execute(text('TRUNCATE mirrors CASCADE'))
    app = create_app(github_client=github, gitea_client=gitea)
    app.testing = True
    with app.test_client() as tclient:
        with app.app_context():
            yield tclient
            close_all_sessions()


@pytest.fixture
def auth():
    return {'Authorization': 'Bearer test-token'}
