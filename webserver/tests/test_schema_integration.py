"""
Integration test for database schema migration.
Tests that new models exist and are wired correctly.
"""
import pytest
from sqlalchemy import inspect
from app.helpers.base_model import db
from app.models.task import Task
from app.models.project import Project
from app.models.api_request import ApiRequest
from app.models.results_backend import ResultsBackend
from app.models.results_repository import ResultsRepository


class TestSchemaMigration:
    """Test that schema migration completed successfully."""

    def test_new_tables_exist(self):
        """Verify new tables were created."""
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()

        assert 'results_repositories' in tables
        assert 'results_backends' in tables
        assert 'api_requests' in tables

    def test_legacy_tables_removed(self):
        """Verify old delivery tables were removed."""
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()

        assert 'delivery_targets' not in tables
        assert 'task_deliveries' not in tables

    def test_task_model_has_new_fields(self):
        """Verify Task model has new fields."""
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('tasks')]

        assert 'api_request_id' in columns
        assert 'git_commit_sha' in columns
        assert 'results_path' in columns
        assert 'trigger_payload' in columns

    def test_project_model_has_results_repository_id(self):
        """Verify Project model has results_repository_id FK."""
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('projects')]

        assert 'results_repository_id' in columns

    def test_model_imports_work(self):
        """Verify all models can be imported."""
        assert Task is not None
        assert Project is not None
        assert ApiRequest is not None
        assert ResultsBackend is not None
        assert ResultsRepository is not None

    def test_task_model_relationships(self):
        """Verify Task model has correct relationships."""
        assert hasattr(Task, 'api_request')
        assert hasattr(Project, 'results_repository')
        assert hasattr(Project, 'results_backend')
        assert hasattr(Project, 'api_requests')

    def test_results_backend_has_backentype(self):
        """Verify ResultsBackend model has BackendType enum."""
        from app.models.results_backend import BackendType

        assert BackendType.GIT.value == 'git'
        assert BackendType.S3.value == 's3'
        assert BackendType.AZURE.value == 'azure'
        assert BackendType.GCP.value == 'gcp'

    def test_timestamps_standardized(self):
        """Verify created_at/updated_at exist on new models."""
        inspector = inspect(db.engine)

        for table in ['results_repositories', 'results_backends', 'api_requests']:
            columns = [col['name'] for col in inspector.get_columns(table)]
            assert 'created_at' in columns, f"{table} missing created_at"
            if table != 'api_requests':  # api_requests has no updated_at
                assert 'updated_at' in columns, f"{table} missing updated_at"


class TestTaskApiEndpoints:
    """Test that Task API endpoints are implemented."""

    def test_health_endpoint_returns_200(self, client):
        """Test /tasks/health endpoint."""
        response = client.get('/tasks/health')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'healthy'
        assert data['database'] == 'connected'

    def test_service_info_endpoint_requires_auth(self, client):
        """Test /tasks/service-info endpoint (requires auth)."""
        response = client.get('/tasks/service-info')
        assert response.status_code == 401  # Unauthorized without token

    def test_validate_endpoint_exists(self, client):
        """Test /tasks/validate endpoint exists."""
        response = client.post('/tasks/validate', json={})
        # Will fail auth or validation, but endpoint should exist
        assert response.status_code in [400, 401]
