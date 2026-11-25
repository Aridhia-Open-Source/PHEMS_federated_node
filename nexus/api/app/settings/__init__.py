"""Nexus API settings, read once per process."""
# pylint: disable=too-few-public-methods

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from pydantic import Field

from fednode.settings import EnvSettings
from app.settings.groups import (
    DatabaseSettings, HttpSettings, NamespacesSettings, NodeSettings, ServicesSettings, TasksSettings,
)


class Settings(EnvSettings):
    """All API settings."""
    node: NodeSettings = Field(default_factory=NodeSettings)
    namespaces: NamespacesSettings = Field(default_factory=NamespacesSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)
    services: ServicesSettings = Field(default_factory=ServicesSettings)
    tasks: TasksSettings = Field(default_factory=TasksSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)


@lru_cache
def get_settings() -> Settings:
    """Build the API settings from the process environment."""
    return Settings()


SettingsDep = Annotated[Settings, Depends(get_settings)]
settings: Settings = get_settings()
