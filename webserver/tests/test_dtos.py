"""
The response shape of every model. These pin the field names and datetime formats the
API returns, and the Dagster wire models in dagster/app/models.py depend on them.
"""
import re

from app.dtos.audit import AuditDTO
from app.dtos.base import page_of
from app.dtos.dataset import CatalogueDTO, DatasetDTO, DictionaryDTO
from app.dtos.project import ProjectDTO
from app.dtos.registry import RegistryDTO
from app.dtos.request import RequestDTO
from app.dtos.task import TaskDTO
from app.dtos.whitelisted_image import WhitelistedImageDTO
from app.models.extras.audit import Audit
from app.models.extras.registry import Registry
from app.models.extras.whitelisted_image import WhitelistedImage
from app.models.project import Project
from app.models.task import Task

WIRE_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class TestProjectDTO:
    def test_fields(self, project):
        assert set(ProjectDTO.from_model(project).dump()) == {
            "id", "name", "description", "default_dataset_id", "enabled",
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
            "id", "project_id", "k8s_secret_name", "k8s_secret_k8s_name", "name", "host", "port", "read_schema", "write_schema", "type",
            "extra_connection_args", "created_at", "updated_at", "slug", "url",
        }

    def test_never_exposes_credentials(self, dataset):
        dumped = DatasetDTO.from_model(dataset).dump()
        assert "username" not in dumped
        assert "password" not in dumped

    def test_slug_and_url_are_derived(self, dataset):
        dumped = DatasetDTO.from_model(dataset).dump()
        assert dumped["slug"] == dataset.slugify_name()
        assert dumped["url"].endswith(f"/datasets/{dumped['slug']}")

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


class TestRequestDTO:
    def test_fields(self, access_request):
        assert set(RequestDTO.from_model(access_request).dump()) == {
            "id", "dataset_id", "project_id", "title", "description", "requested_by",
            "project_name", "status", "proj_start", "proj_end", "created_at", "updated_at",
        }

    def test_datetimes_use_the_wire_format(self, access_request):
        dumped = RequestDTO.from_model(access_request).dump()
        for field in ("proj_start", "proj_end", "created_at", "updated_at"):
            assert WIRE_DATETIME.match(dumped[field]), field


class TestRegistryDTO:
    def test_fields(self):
        registry = Registry(url="registry.example.com", username="user", password="pass")
        registry.id = 1
        assert RegistryDTO.from_model(registry).dump() == {
            "id": 1, "url": "registry.example.com", "needs_auth": True, "active": True,
        }

    def test_never_exposes_credentials(self):
        registry = Registry(url="registry.example.com", username="user", password="pass")
        registry.id = 1
        dumped = RegistryDTO.from_model(registry).dump()
        assert "username" not in dumped
        assert "password" not in dumped


class TestWhitelistedImageDTO:
    def test_fields(self):
        image = WhitelistedImage(name="alpine", registry=None, project_id=1, tag="latest")
        image.id = 1
        assert WhitelistedImageDTO.from_model(image).dump() == {
            "id": 1, "registry_id": None, "project_id": 1, "name": "alpine",
            "tag": "latest", "sha": None,
        }


class TestAuditDTO:
    def test_fields(self):
        audit = Audit("127.0.0.1", "GET", "/datasets", "user", status_code=200)
        audit.id = 1
        dumped = AuditDTO.from_model(audit).dump()
        assert set(dumped) == {
            "id", "ip_address", "http_method", "endpoint", "requested_by", "status_code",
            "api_function", "details", "event_time",
        }
        assert dumped["status_code"] == 200
        assert dumped["details"] is None
        assert WIRE_DATETIME.match(dumped["event_time"])


class TestTaskDTO:
    def test_fields(self):
        task = Task(
            name="task", docker_image="alpine:latest", requested_by="user", dataset_id=None, project_id=1,
            trigger_id=1, spec={"image": "alpine:latest"}
        )
        task.id = 1
        dumped = TaskDTO.from_model(task).dump()
        assert set(dumped) == {
            "id", "name", "docker_image", "spec", "attempt", "status", "created_at", "updated_at",
            "requested_by", "dataset_id", "project_id", "trigger_id",
            "dagster_run_id", "exit_code", "started_at", "completed_at",
        }
        assert dumped["status"] == "PENDING"
        assert dumped["attempt"] == 1
        assert dumped["spec"] == {"image": "alpine:latest"}
        assert dumped["trigger_id"] == 1
        assert WIRE_DATETIME.match(dumped["created_at"])


class TestPageOf:
    def test_envelope(self, project):
        page = page_of(Project.query.paginate(page=1, per_page=10), ProjectDTO)
        assert set(page) == {"items", "page", "per_page", "total", "pages"}
        assert page["page"] == 1
        assert page["per_page"] == 10
        assert page["total"] == 1
        assert page["pages"] == 1

    def test_items_are_dumped_dtos(self, project):
        page = page_of(Project.query.paginate(page=1, per_page=10), ProjectDTO)
        assert page["items"] == [ProjectDTO.from_model(project).dump()]

    def test_empty(self, client):
        page = page_of(Project.query.paginate(page=1, per_page=10), ProjectDTO)
        assert page["items"] == []
        assert page["total"] == 0
