"""Dagster settings, loaded lazily so sensor discovery needs only sensor settings."""
from functools import cached_property

from fednode.settings import EnvSettings
from app.settings.groups import (
    ArtifactsSettings, HttpSettings, NamespacesSettings, NodeSettings, ResultsSettings, SensorsSettings,
    ServicesSettings, TasksSettings,
)


class Settings(EnvSettings):
    @cached_property
    def node(self) -> NodeSettings:
        return NodeSettings()

    @cached_property
    def namespaces(self) -> NamespacesSettings:
        return NamespacesSettings()

    @cached_property
    def http(self) -> HttpSettings:
        return HttpSettings()

    @cached_property
    def services(self) -> ServicesSettings:
        return ServicesSettings()

    @cached_property
    def artifacts(self) -> ArtifactsSettings:
        return ArtifactsSettings()

    @cached_property
    def tasks(self) -> TasksSettings:
        return TasksSettings()

    @cached_property
    def results(self) -> ResultsSettings:
        return ResultsSettings()

    @cached_property
    def sensors(self) -> SensorsSettings:
        return SensorsSettings()


settings = Settings()
