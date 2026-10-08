from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx, RunStatusSensorContext

from app.backend import BackendAPI
from app.config import ResultsDeliveryConfig
from app.definitions.jobs import k8s_pipes_job
from app.definitions.sensors.git.base import GitAPIFactory
from app.delivery.results import ResultsDelivery

MIN_SENSOR_INTERVAL_SECONDS = 10


@dg.op(config_schema={"task_id": dg.Field(int)}, required_resource_keys={"backend_api", "git_apis"})
def deliver_results(context: OpExecCtx):
    """Deliver the results of a task to its project's results repository."""
    ResultsDelivery(
        backend_api=cast(BackendAPI, context.resources.backend_api),
        git_apis=cast(GitAPIFactory, context.resources.git_apis),
        config=ResultsDeliveryConfig(),
        log=context.log,
    )(context.op_config["task_id"])


@dg.job
def deliver_results_job():
    """
    Runs in a run pod, the only place with the artifacts volume. Its tags are
    trigger=delivery and delivery_task_id, never trigger=task or task_id: the run-status
    sensors act on those, and a run of this job must not change the task or be mistaken
    for its run.
    """
    deliver_results()


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    default_status=dg.DefaultSensorStatus.STOPPED,
    monitored_jobs=[k8s_pipes_job],
    request_job=deliver_results_job,
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
)
def task_results_delivery_sensor(context: RunStatusSensorContext):
    """
    Launch the delivery of a task's results when its run succeeds. It fires once per task
    attempt, so a failed delivery is not retried by itself: re-launch deliver_results_job by
    hand, and it resumes from the state its result reached.
    """
    tags = context.dagster_run.tags
    if tags.get("trigger") != "task":
        return

    task_id = tags["task_id"]
    return dg.RunRequest(
        run_key=f"deliver/{task_id}/{tags['attempt']}",
        tags={"trigger": "delivery", "delivery_task_id": task_id},
        run_config={"ops": {"deliver_results": {"config": {"task_id": int(task_id)}}}},
    )
