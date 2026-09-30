from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx

from app.backend import BackendAPI
from app.definitions.sensors.task_request.launcher import TaskRequestLauncherSensor

MIN_SENSOR_INTERVAL_SECONDS = 10


@dg.sensor(
    minimum_interval_seconds=MIN_SENSOR_INTERVAL_SECONDS,
    default_status=dg.DefaultSensorStatus.STOPPED,
    required_resource_keys={"backend_api"},
    job_name="k8s_pipes_job",
)
def task_request_sensor(context: OpExecCtx):
    """
    Sensor that launches k8s_pipes_job for the queued task requests of enabled projects,
    whether they came from a merged pull request or from the API.
    """
    sensor = TaskRequestLauncherSensor(
        context=context,
        backend_api=cast(BackendAPI, context.resources.backend_api),
    )
    yield from sensor()


SENSORS = [
    task_request_sensor,
]

JOBS = []
