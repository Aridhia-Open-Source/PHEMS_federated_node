import pytest
from pydantic import ValidationError
from pathlib import Path

from app.clients.keycloak import read_secret
from app.helpers.exceptions import KeycloakError
from app.settings import Settings, settings


def test_settings_read_new_environment_names(monkeypatch):
    monkeypatch.setenv("NODE_HOSTNAME", "node.example")
    monkeypatch.setenv("SERVICES_DAGSTER_URI", "http://dagster.example")
    monkeypatch.setenv("DATABASE_HOST", "database.example")
    monkeypatch.setenv("HTTP_READ_TIMEOUT", "27")

    configured = Settings()

    assert configured.node.hostname == "node.example"
    assert configured.services.dagster.uri == "http://dagster.example"
    assert configured.database.host == "database.example"
    assert configured.http.read_timeout == 27


def test_dagster_uri_is_required_even_when_not_used(monkeypatch):
    monkeypatch.delenv("SERVICES_DAGSTER_URI", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_missing_keycloak_credential_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(settings.services.keycloak, "secrets_path", str(tmp_path))
    with pytest.raises(KeycloakError):
        read_secret("missing", None)
    assert read_secret("missing", "fallback") == "fallback"


def test_unreadable_keycloak_credential_does_not_use_fallback(monkeypatch):
    def unreadable(*_args, **_kwargs):
        raise PermissionError("unreadable")

    monkeypatch.setattr(Path, "read_text", unreadable)
    with pytest.raises(PermissionError):
        read_secret("mounted", "fallback")
