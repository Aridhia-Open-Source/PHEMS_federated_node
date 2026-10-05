"""
Commands to turn the Dagster sensors on and off, and to see what they are doing. Needs the
Dagster webserver port-forwarded.
"""

import logging

import click

from fncli.cmds.common import DagsterConfig
from fncli.dagster.sensors import DagsterAPI

logger = logging.getLogger("sensor")

SENSORS = {
    "ingest": "git_pull_request_ingest_sensor",
    "evaluate": "git_pull_request_evaluate_sensor",
    "launcher": "task_launcher_sensor",
}

sensor_option = click.option(
    "--sensor",
    type=click.Choice(list(SENSORS)),
    default="ingest",
    show_default=True,
    help="Which sensor to act on.",
)


@click.command("start-sensor")
@sensor_option
def start_sensor_command(sensor):
    """Start a Dagster sensor (no-op if it is running)."""
    api = DagsterAPI(DagsterConfig().dagster_url)
    status = api.start_sensor(SENSORS[sensor])
    logger.info(f"Started sensor {SENSORS[sensor]} ({status})")


@click.command("stop-sensor")
@sensor_option
def stop_sensor_command(sensor):
    """Stop a Dagster sensor (no-op if it is stopped)."""
    api = DagsterAPI(DagsterConfig().dagster_url)
    status = api.stop_sensor(SENSORS[sensor])
    logger.info(f"Stopped sensor {SENSORS[sensor]} ({status})")


@click.command("sensor-status")
def sensor_status_command():
    """Show each sensor's status and its last 3 ticks."""
    api = DagsterAPI(DagsterConfig().dagster_url)
    for name in SENSORS.values():
        state = api.get_sensor_state(name)
        logger.info(f"{name}: {state['status']}")
        for tick in state["ticks"]:
            detail = tick["skipReason"] or (tick["error"] or {}).get("message") or ""
            logger.info(f"  {tick['status']} {detail}".rstrip())


COMMANDS = [start_sensor_command, stop_sensor_command, sensor_status_command]
