from abc import ABC, abstractmethod
from typing import Union

from dagster import Any, OpExecutionContext as OpExecCtx, RunStatusSensorContext


class BaseSensor(ABC):
    """Base class for all sensors providing common scaffolding."""

    def __init__(self, context: Union[OpExecCtx, RunStatusSensorContext]):
        self.context = context
        self.log = context.log

    def setup(self, *args: Any, **kwds: Any) -> Any:
        pass

    @abstractmethod
    def __call__(self, *args: Any, **kwds: Any) -> Any:
        """Run the sensor; every concrete sensor implements this."""
