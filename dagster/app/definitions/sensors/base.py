import time
from abc import ABC, abstractmethod
from typing import Any, Iterable, Union

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx, RunStatusSensorContext

from app.config import SENSOR_RETRY_INTERVAL_SECONDS

IN_FLIGHT = [dg.DagsterRunStatus.NOT_STARTED, dg.DagsterRunStatus.QUEUED, dg.DagsterRunStatus.STARTING,
             dg.DagsterRunStatus.STARTED]


def run_key(kind: str, item_id: Any = None, state: Any = None) -> str:
    """
    The run key kind/item_id/state/slot, where the slot is the current retry interval. A part
    that is None is left out.

    A new state gives a new key at once. A failed run with an unchanged state is retried once per
    retry interval, because the slot changes: run keys are permanent per sensor in Dagster, so a
    key that never changed would never launch again.
    """
    slot = int(time.time() // SENSOR_RETRY_INTERVAL_SECONDS)
    return "/".join(str(part) for part in (kind, item_id, state, slot) if part is not None)


def run_in_flight(context: Union[OpExecCtx, dg.SensorEvaluationContext], job: Any, tags: dict[str, str]) -> bool:
    """Whether a run of the job with these tags is queued or started."""
    runs = context.instance.get_runs(
        filters=dg.RunsFilter(job_name=job.name, tags=tags, statuses=IN_FLIGHT),
        limit=1,
    )
    return bool(runs)


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


class LaunchingSensor(BaseSensor):
    """
    A sensor that launches one run of a job per item that is ready. A subclass says which items
    there are, whether one is ready, and how to launch it, and sets job, failure_label and
    skip_message.
    """

    job: Any
    failure_label: str
    skip_message: str

    @abstractmethod
    def items(self) -> Iterable[Any]:
        """The things that may need a run, e.g. repositories."""

    @abstractmethod
    def describe(self, item: Any) -> str:
        """Names the item in logs and in the tick's failure message."""

    @abstractmethod
    def tags(self, item: Any) -> dict[str, str]:
        """The tags of the item's run, which also find its runs in flight."""

    @abstractmethod
    def ready(self, item: Any) -> bool:
        """Whether the item needs a run now. May call the backend or the git provider."""

    @abstractmethod
    def run_request(self, item: Any) -> dg.RunRequest:
        """The run for a ready item, its key built with run_key."""

    def __call__(self):
        """
        Yields a RunRequest per ready item that has no run in flight, or a SkipReason when
        there is none.

        A failing item is logged and the others still launch. Dagster drops what a failing tick
        yielded, so the tick only fails, naming the items, when nothing launched: one broken
        item must not starve the rest.
        """
        launched = 0
        failed = []
        for item in self.items():
            try:
                if run_in_flight(self.context, self.job, self.tags(item)):
                    self.log.info(f"{self.describe(item)} is already in flight")
                    continue
                if not self.ready(item):
                    continue
                request = self.run_request(item)
            except Exception:  # pylint: disable=broad-exception-caught  # one item must not stop the others
                self.log.exception(f"Checking {self.describe(item)} failed")
                failed.append(self.describe(item))
                continue
            yield request
            launched += 1
        if failed:
            message = f"{self.failure_label} failed for {', '.join(failed)}"
            if not launched:
                raise RuntimeError(message)
            self.log.error(f"{message}; launched {launched} runs for the others")
        if not launched and not failed:
            yield dg.SkipReason(self.skip_message)
