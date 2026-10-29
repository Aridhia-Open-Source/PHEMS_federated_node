"""
The response shape of every model. These pin the field names and datetime formats the
API returns, and the Dagster wire models in dagster/app/models.py depend on them.
"""
import re

from app.dtos.dataset import CatalogueDTO, DatasetDTO, DictionaryDTO
from app.dtos.project import ProjectDTO
from app.dtos.task import TaskDTO
from app.models.task import Task

WIRE_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class TestProjectDTO:
    def test_fields(self, project):
        assert set(ProjectDTO.from_model(project).dump()) == {
            "id", "name", "description", "default_dataset_id", "enabled", "revoked",
            "created_at", "updated_at",
        }

    def test_values(self, project):
        dumped = ProjectDTO.from_model(project).dump()
        assert dumped["id"] == project.id
        assert dumped["name"] == "TestProject"
        assert dumped["description"] is None

    def test_datetimes_use_the_wire_format(self, project):
        dumped = ProjectDTO.from_model(project).dump()
        assert WIRE_DATETIME.match(dumped["created_at"])
        assert WIRE_DATETIME.match(dumped["updated_at"])


class TestDatasetDTO:
    def test_fields(self, dataset):
        assert set(DatasetDTO.from_model(dataset).dump()) == {
            "id", "secret", "name", "host", "port", "read_schema", "write_schema", "type",
            "extra_connection_args", "created_at", "updated_at", "slug", "url", "enabled",
            "revoked",
        }

    def test_never_exposes_credentials(self, dataset):
        dumped = DatasetDTO.from_model(dataset).dump()
        assert "username" not in dumped
        assert "password" not in dumped

    def test_slug_and_url_are_derived(self, dataset):
        dumped = DatasetDTO.from_model(dataset).dump()
        assert dumped["slug"] == dataset.slugify_name()
        assert dumped["url"].endswith(f"/global/datasets/{dataset.id}")

    def test_datetimes_use_the_wire_format(self, dataset):
        dumped = DatasetDTO.from_model(dataset).dump()
        assert WIRE_DATETIME.match(dumped["created_at"])
        assert WIRE_DATETIME.match(dumped["updated_at"])


class TestCatalogueDTO:
    def test_fields(self, catalogue):
        assert set(CatalogueDTO.from_model(catalogue).dump()) == {
            "id", "dataset_id", "version", "title", "description", "created_at", "updated_at",
        }

    def test_values(self, catalogue):
        dumped = CatalogueDTO.from_model(catalogue).dump()
        assert dumped["title"] == "new catalogue"
        assert dumped["dataset_id"] == catalogue.dataset_id


class TestDictionaryDTO:
    def test_fields(self, dictionary):
        assert set(DictionaryDTO.from_model(dictionary[0]).dump()) == {
            "id", "dataset_id", "table_name", "field_name", "label", "description",
            "created_at", "updated_at",
        }

    def test_values(self, dictionary):
        dumped = DictionaryDTO.from_model(dictionary[0]).dump()
        assert dumped["table_name"] == "patients"
        assert dumped["field_name"] == "id"
        assert dumped["label"] == "p_id"



class TestTaskDTO:
    def test_fields(self):
        task = Task(
            name="task", requested_by="user", project_id=1, trigger_id=1,
            spec={"image": "alpine:latest", "dataset_id": None, "env": {"K": "v"}, "resources": {"limits": {"cpu": "1"}}}
        )
        task.id = 1
        dumped = TaskDTO.from_model(task).dump()
        assert set(dumped) == {
            "id", "name", "spec", "attempt", "status", "created_at", "updated_at",
            "requested_by", "project_id", "trigger_id",
            "executor_run_id", "exit_code", "started_at", "completed_at", "state_cause", "config_hash",
        }
        assert dumped["status"] == "PENDING"
        assert dumped["attempt"] == 1
        assert dumped["spec"] == {
            "image": "alpine:latest", "dataset_id": None, "env": {"K": "v"}, "resources": {"limits": {"cpu": "1"}}
        }
        assert dumped["trigger_id"] == 1
        assert WIRE_DATETIME.match(dumped["created_at"])
