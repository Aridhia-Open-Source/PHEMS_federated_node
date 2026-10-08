"""
The response shape of every model. These pin the field names and datetime formats the
API returns, and the Dagster wire models in dagster/app/models.py depend on them.
"""
import re

from app.dtos.audit import AuditDTO
from app.dtos.dataset import CatalogueDTO, DatasetDTO, DictionaryDTO
from app.dtos.registry import RegistryDTO
from app.models.extras.audit import Audit
from app.models.extras.registry import Registry

WIRE_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


class TestDatasetDTO:
    def test_fields(self, dataset):
        assert set(DatasetDTO.from_model(dataset).dump()) == {
            "id", "project_id", "secret", "name", "host", "port", "read_schema", "write_schema", "type",
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
