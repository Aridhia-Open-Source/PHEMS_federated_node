"""
Commands to turn the Dagster sensors on and off, and to see what they are doing. Needs the
Dagster webserver port-forwarded.
"""

import logging

import click

from fncli.cmds.common import DagsterConfig
from fncli.sensors import DagsterAPI

logger = logging.getLogger("sensor")

# The run-status sensors move a task on as its run does, from the moment they start.
RUN_STATUS_SENSORS = [
    "task_queued_sensor",
    "task_started_sensor",
    "task_success_sensor",
    "task_failure_sensor",
    "task_canceled_sensor",
]
# Safety net: every tick it sets each unfinished task to the current status of its run, so a missed
# run-status event is repaired and the start order does not matter.
RECONCILE_SENSOR = "task_reconcile_sensor"
DELIVERY_SENSOR = "task_results_delivery_sensor"
# Polls the pushed and opened results and copies their PR's state (opened, merged, closed) onto the result.
RESULTS_PR_SYNC_SENSOR = "results_pull_request_sync_sensor"
# Relaunches the deliveries that failed.
DELIVERY_RETRY_SENSOR = "results_delivery_retry_sensor"
# Start order does not matter; stopping goes the other way round.
ALL_SENSORS = [
    *RUN_STATUS_SENSORS,
    RECONCILE_SENSOR,
    DELIVERY_SENSOR,
    RESULTS_PR_SYNC_SENSOR,
    DELIVERY_RETRY_SENSOR,
    "git_pull_request_ingest_sensor",
    "git_pull_request_evaluate_sensor",
    "task_launcher_sensor",
]
SENSORS = {
    "ingest": ["git_pull_request_ingest_sensor"],
    "evaluate": ["git_pull_request_evaluate_sensor"],
    "launcher": ["task_launcher_sensor"],
    "status": [*RUN_STATUS_SENSORS, RECONCILE_SENSOR],
    "delivery": [DELIVERY_SENSOR, RESULTS_PR_SYNC_SENSOR, DELIVERY_RETRY_SENSOR],
    "all": ALL_SENSORS,
}

def sensor_options(command):
    command = click.option(
        "--name",
        type=click.Choice(ALL_SENSORS),
        default=None,
        help="One sensor, by its name.",
    )(command)
    return click.option(
        "--group",
        type=click.Choice(list(SENSORS)),
        default=None,
        help="A group of sensors: 'ingest', 'evaluate', 'launcher', 'status' (the run-status and "
        "reconcile sensors), 'delivery', or 'all'.",
    )(command)


def selected_sensors(group: str | None, name: str | None) -> list[str]:
    if (group is None) == (name is None):
        raise click.UsageError("Give --group or --name, one of them.")
    return [name] if name else SENSORS[group]


@click.command("start-sensor")
@sensor_options
def start_sensor_command(group, name):
    """Start a group of Dagster sensors, or one by name (no-op if running)."""
    api = DagsterAPI(DagsterConfig().dagster_url)
    for sensor in selected_sensors(group, name):
        logger.info(f"Started sensor {sensor} ({api.start_sensor(sensor)})")


@click.command("stop-sensor")
@sensor_options
def stop_sensor_command(group, name):
    """Stop a group of Dagster sensors, or one by name (no-op if stopped). A group stops in reverse order."""
    api = DagsterAPI(DagsterConfig().dagster_url)
    for sensor in reversed(selected_sensors(group, name)):
        logger.info(f"Stopped sensor {sensor} ({api.stop_sensor(sensor)})")


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
