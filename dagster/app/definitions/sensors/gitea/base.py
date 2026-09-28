from typing import Union

from app.definitions.sensors.base import BaseSensor
from app.backend import BackendAPI
from app.gitea import GiteaAPI

from dagster import OpExecutionContext as OpExecCtx, RunStatusSensorContext


class GiteaSensor(BaseSensor):
    """Base class for Gitea-related sensors."""

    def __init__(
        self,
        context: Union[OpExecCtx, RunStatusSensorContext],
        backend_api: BackendAPI,
        gitea_api: GiteaAPI,
    ):
        super().__init__(context)
        self.backend_api = backend_api
        self.gitea_api = gitea_api
