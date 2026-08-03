"""Model registry — lazy-initialized on first access."""
from functools import cached_property


class ModelRegistry:
    """Registry of all app models. Cached on first access."""

    @cached_property
    def Audit(self):
        from app.models.audit import Audit
        return Audit

    @cached_property
    def Catalogue(self):
        from app.models.catalogue import Catalogue
        return Catalogue

    @cached_property
    def Container(self):
        from app.models.container import Container
        return Container

    @cached_property
    def Dataset(self):
        from app.models.dataset import Dataset
        return Dataset

    @cached_property
    def Dictionary(self):
        from app.models.dictionary import Dictionary
        return Dictionary

    @cached_property
    def PullRequest(self):
        from app.models.pull_request import PullRequest
        return PullRequest

    @cached_property
    def Registry(self):
        from app.models.registry import Registry
        return Registry

    @cached_property
    def Repository(self):
        from app.models.repository import Repository
        return Repository

    @cached_property
    def Request(self):
        from app.models.request import Request
        return Request

    @cached_property
    def Task(self):
        from app.models.task import Task
        return Task


Models = ModelRegistry()
