import pytest
from sqlalchemy import inspect
from alembic.config import Config
from alembic import command
from app.helpers.base_model import engine


def test_health_endpoint(client):
    """Test that GET /health returns 200."""
    response = client.get('/health')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'ok'


def test_migration_creates_tables():
    """Test that Alembic migration creates all 5 tables."""
    # Run migrations
    config = Config('alembic.ini')
    command.upgrade(config, 'head')

    # Inspect the database schema
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    # Verify all 5 tables exist
    expected_tables = {
        'mirrors',
        'mirror_state',
        'mirrored_pull_requests',
        'webhooks',
        'webhook_deliveries'
    }

    assert expected_tables.issubset(table_names), f"Missing tables: {expected_tables - table_names}"
