from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx, RunStatusSensorContext

from app.backend import BackendAPI
from app.config import DEFAULT_SENSOR_STATUS, DELIVERY_MAX_ATTEMPTS, MIN_SENSOR_INTERVAL_SECONDS, ResultsDeliveryConfig
from app.definitions.jobs import k8s_pipes_job
from app.definitions.sensors.base import LaunchingSensor, run_key
from app.definitions.sensors.git.base import GitAPIFactory
from app.delivery.results import FINAL, ResultsDelivery
from app.models import PullRequestResult, ResultState


@dg.op(config_schema={"project_id": dg.Field(int), "task_id": dg.Field(int), "run_id": dg.Field(str)}, required_resource_keys={"backend_api", "git_apis"})
def deliver_results(context: OpExecCtx):
    """Deliver the results of a task to its project's results repository."""
    ResultsDelivery(
        backend_api=cast(BackendAPI, context.resources.backend_api),
        git_apis=cast(GitAPIFactory, context.resources.git_apis),
        config=ResultsDeliveryConfig(),
        log=context.log,
    )(
        context.op_config["project_id"], context.op_config["task_id"], context.op_config["run_id"]
    )


@dg.job
def deliver_results_job():
    """
    Runs in a run pod, the only place with the artifacts volume. Its tags are
    trigger=delivery and delivery_task_id, never trigger=task or task_id: the run-status
    sensors act on those, and a run of this job must not change the task or be mistaken
    for its run.
    """
    deliver_results()  # pylint: disable=no-value-for-parameter  # Dagster injects context


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=DEFAULT_SENSOR_STATUS,
    monitored_jobs=[k8s_pipes_job],
    request_job=deliver_results_job,
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_results_delivery_sensor(context: RunStatusSensorContext):
    """
    Launch the delivery of a task's results when its run succeeds. It fires once per task
    attempt, so the run key deliver/<task>/<attempt> is exactly once. A failed delivery is
    retried by results_delivery_retry_sensor, up to DAGSTER_DELIVERY_MAX_ATTEMPTS attempts.
    """
    tags = context.dagster_run.tags
    if tags.get("trigger") != "task":
        return None

    task_id = tags["task_id"]
    return dg.RunRequest(
        run_key=f"deliver/{task_id}/{tags['attempt']}",
        tags={"trigger": "delivery", "delivery_task_id": task_id},
        run_config={"ops": {"deliver_results": {"config": {
            "project_id": int(tags["project_id"]), "task_id": int(task_id), "run_id": context.dagster_run.run_id
        }}}},
    )


class ResultsDeliveryRetrySensor(LaunchingSensor):
    """
    Relaunches deliver_results_job for each result whose delivery failed and is not final, until it
    has DAGSTER_DELIVERY_MAX_ATTEMPTS failed attempts: after that it stays FAILED until relaunched by
    hand (reset `attempts` with a PATCH, or re-run deliver_results_job). The
    job resumes from the step the result reached. Only results whose project results repository
    is active are retried. The run key names the result and has no state, see run_key: a failing
    delivery is retried at most once per retry interval.
    A delivery with a run still queued or started is skipped, whichever sensor launched it.
    """

    job = deliver_results_job
    failure_label = "Delivery retry"
    skip_message = "No failed deliveries to retry."

    def __init__(self, context, backend_api: BackendAPI):
        super().__init__(context)
        self.backend_api = backend_api
        self.run_ids: dict[int, str] = {}

    def items(self) -> list[PullRequestResult]:
        return [
            result
            for project in self.backend_api.get_projects()
            for result in self.backend_api.get_results_by_state(project.id, ResultState.FAILED.value, active_resource=True)
            if result.step not in FINAL and result.attempts < DELIVERY_MAX_ATTEMPTS
        ]

    def describe(self, item: PullRequestResult) -> str:
        return f"Delivery of results {item.id} of task {item.task_id}"

    def tags(self, item: PullRequestResult) -> dict[str, str]:
        return {"trigger": "delivery", "delivery_task_id": str(item.task_id)}

    def ready(self, item: PullRequestResult) -> bool:
        """Always, noting the run id of the task's run, whose artifacts the delivery zips."""
        self.run_ids[item.id] = self.backend_api.get_task(item.project_id, item.task_id).executor_run_id
        return True

    def run_request(self, item: PullRequestResult) -> dg.RunRequest:
        return dg.RunRequest(
            run_key=run_key("deliver-retry", item.id),
            tags=self.tags(item),
            run_config={"ops": {deliver_results.name: {"config": {
                "project_id": item.project_id, "task_id": item.task_id, "run_id": self.run_ids[item.id]
            }}}},
        )


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=DEFAULT_SENSOR_STATUS,
    required_resource_keys={"backend_api"},
    job=deliver_results_job,
)
def results_delivery_retry_sensor(context: dg.SensorEvaluationContext):
    """Relaunch deliver_results_job for the results whose delivery failed, see ResultsDeliveryRetrySensor."""
    sensor = ResultsDeliveryRetrySensor(context=context, backend_api=cast(BackendAPI, context.resources.backend_api))
    yield from sensor()
