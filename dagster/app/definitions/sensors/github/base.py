from typing import Union

from app.definitions.sensors.base import BaseSensor
from app.backend import BackendAPI
from app.github import GithubAPI

from dagster import OpExecutionContext as OpExecCtx, RunStatusSensorContext


class GithubSensor(BaseSensor):
    """Base class for GitHub-related sensors."""

    def __init__(
        self,
        context: Union[OpExecCtx, RunStatusSensorContext],
        backend_api: BackendAPI,
        github_api: GithubAPI,
    ):
        super().__init__(context)
        self.backend_api = backend_api
        self.github_api = github_api
