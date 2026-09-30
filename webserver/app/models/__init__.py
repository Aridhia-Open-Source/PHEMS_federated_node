"""Model registry — lazy-initialized on first access."""
from functools import cached_property
from sqlalchemy import Column, DateTime
from sqlalchemy.sql import func


class ModelRegistry:
    """Registry of all app models. Cached on first access."""

    @cached_property
    def Audit(self):
        from app.models.extras.audit import Audit
        return Audit

    @cached_property
    def Catalogue(self):
        from app.models.extras.catalogue import Catalogue
        return Catalogue

    @cached_property
    def Dataset(self):
        from app.models.dataset import Dataset
        return Dataset

    @cached_property
    def Dictionary(self):
        from app.models.extras.dictionary import Dictionary
        return Dictionary

    @cached_property
    def Project(self):
        from app.models.project import Project
        return Project

    @cached_property
    def PullRequest(self):
        from app.models.pull_request import PullRequest
        return PullRequest

    @cached_property
    def Registry(self):
        from app.models.extras.registry import Registry
        return Registry

    @cached_property
    def Request(self):
        from app.models.extras.request import Request
        return Request

    @cached_property
    def Task(self):
        from app.models.task import Task
        return Task

    @cached_property
    def WhitelistedImage(self):
        from app.models.extras.whitelisted_image import WhitelistedImage
        return WhitelistedImage

    @cached_property
    def TriggerRepository(self):
        from app.models.trigger_repository import TriggerRepository
        return TriggerRepository

    @cached_property
    def ResultsRepository(self):
        from app.models.results_repository import ResultsRepository
        return ResultsRepository

    @cached_property
    def ResultsBackend(self):
        from app.models.results_backend import ResultsBackend
        return ResultsBackend

    @cached_property
    def ApiRequest(self):
        from app.models.api_request import ApiRequest
        return ApiRequest

    @cached_property
    def TaskRequest(self):
        from app.models.task_request import TaskRequest
        return TaskRequest

    @cached_property
    def K8sSecret(self):
        from app.models.k8s_secret import K8sSecret
        return K8sSecret


class SqlaColumn:
    """Factory for standardized column definitions shared across models."""

    def created_at(self, **kwargs) -> Column:
        return Column(
            DateTime(timezone=False),
            nullable=False,
            server_default=func.now(),
            **kwargs
        )

    def updated_at(self, **kwargs) -> Column:
        return Column(
            DateTime(timezone=False),
            nullable=False,
            server_default=func.now(),
            onupdate=func.now(),
            **kwargs
        )


Models = ModelRegistry()
sqla_column = SqlaColumn()
__all__ = ['sqla_column', 'SqlaColumn', 'ModelRegistry', 'Models']


# Force eager import of all models to register them with SQLA before mapper configuration
# This ensures string-based relationships can be resolved to avoid circular dependencies.
_ = (
    Models.Audit,
    Models.Catalogue,
    Models.Dataset,
    Models.Dictionary,
    Models.Project,
    Models.PullRequest,
    Models.Registry,
    Models.Request,
    Models.Task,
    Models.WhitelistedImage,
    Models.TriggerRepository,
    Models.ResultsRepository,
    Models.ResultsBackend,
    Models.ApiRequest,
    Models.TaskRequest,
    Models.K8sSecret,
)
