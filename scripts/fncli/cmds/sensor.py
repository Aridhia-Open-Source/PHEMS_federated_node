"""
Commands to turn the Dagster sensors on and off, and to see what they are doing. Needs the
Dagster webserver port-forwarded.
"""

import logging

import click

from fncli.cmds.common import DagsterConfig
from fncli.dagster.sensors import DagsterAPI

logger = logging.getLogger("sensor")

# The run-status sensors move a task on as its run does, but only see events from the moment
# they start. They must be running before the launcher, or a run that finishes first stays
# PENDING on its task for good (its run key stops it being launched again).
RUN_STATUS_SENSORS = [
    "task_queued_sensor",
    "task_started_sensor",
    "task_success_sensor",
    "task_failure_sensor",
    "task_canceled_sensor",
]
# The delivery sensor is a run-status sensor too (it acts when a task's run succeeds), so it
# starts before the launcher as well.
DELIVERY_SENSOR = "task_results_delivery_sensor"
# Polls the open results PRs and copies their state (merged, closed) onto the TaskResult.
RESULTS_PR_SYNC_SENSOR = "results_pull_request_sync_sensor"
# In start order; stopping goes the other way round.
ALL_SENSORS = [
    *RUN_STATUS_SENSORS,
    DELIVERY_SENSOR,
    RESULTS_PR_SYNC_SENSOR,
    "git_pull_request_ingest_sensor",
    "git_pull_request_evaluate_sensor",
    "task_launcher_sensor",
]
SENSORS = {
    "ingest": ["git_pull_request_ingest_sensor"],
    "evaluate": ["git_pull_request_evaluate_sensor"],
    "launcher": ["task_launcher_sensor"],
    "status": RUN_STATUS_SENSORS,
    "delivery": [DELIVERY_SENSOR, RESULTS_PR_SYNC_SENSOR],
    "all": ALL_SENSORS,
}

sensor_option = click.option(
    "--sensor",
    type=click.Choice(list(SENSORS)),
    default="ingest",
    show_default=True,
    help="Which sensor to act on: one, 'status' (the run-status sensors), 'delivery' or 'all'.",
)


@click.command("start-sensor")
@sensor_option
def start_sensor_command(sensor):
    """Start Dagster sensors (no-op if running). 'all' starts the run-status sensors first."""
    api = DagsterAPI(DagsterConfig().dagster_url)
    for name in SENSORS[sensor]:
        logger.info(f"Started sensor {name} ({api.start_sensor(name)})")


@click.command("stop-sensor")
@sensor_option
def stop_sensor_command(sensor):
    """Stop Dagster sensors (no-op if stopped). 'all' stops the launcher first."""
    api = DagsterAPI(DagsterConfig().dagster_url)
    for name in reversed(SENSORS[sensor]):
        logger.info(f"Stopped sensor {name} ({api.stop_sensor(name)})")


@click.command("sensor-status")
def sensor_status_command():
    """Show every sensor's status and its last 3 ticks."""
    api = DagsterAPI(DagsterConfig().dagster_url)
    for name in ALL_SENSORS:
        state = api.get_sensor_state(name)
        logger.info(f"{name}: {state['status']}")
        for tick in state["ticks"]:
            detail = tick["skipReason"] or (tick["error"] or {}).get("message") or ""
            logger.info(f"  {tick['status']} {detail}".rstrip())


COMMANDS = [start_sensor_command, stop_sensor_command, sensor_status_command]
