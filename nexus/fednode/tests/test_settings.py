import pytest
from pydantic import ValidationError

from fednode.settings import DatabaseSettings, NodeSettings


class RequiredNode(NodeSettings):
    hostname: str


def test_shared_settings_use_their_path_prefix(monkeypatch):
    monkeypatch.setenv("NODE_HOSTNAME", "node.example")
    monkeypatch.setenv("DATABASE_HOST", "db.example")
    monkeypatch.setenv("PGHOST", "old.example")

    assert RequiredNode().hostname == "node.example"
    assert DatabaseSettings().host == "db.example"


def test_services_can_require_a_shared_field(monkeypatch):
    monkeypatch.delenv("NODE_HOSTNAME", raising=False)

    assert NodeSettings().hostname is None
    with pytest.raises(ValidationError):
        RequiredNode()
