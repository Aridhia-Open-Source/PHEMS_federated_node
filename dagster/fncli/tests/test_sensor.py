import click
import pytest
from unittest.mock import MagicMock, patch

from fncli.cmds.sensor import ALL_SENSORS, RUN_STATUS_SENSORS, SENSORS, start_sensor_command, stop_sensor_command


def test_the_delivery_sensors_are_selectable_and_in_all():
    assert SENSORS["delivery"] == [
        "task_results_delivery_sensor", "results_pull_request_sync_sensor", "results_delivery_retry_sensor"
    ]
    assert "task_results_delivery_sensor" in SENSORS["all"]
    assert "results_pull_request_sync_sensor" in SENSORS["all"]
    assert "results_delivery_retry_sensor" in SENSORS["all"]


def test_the_reconcile_sensor_is_selectable_and_in_all():
    assert "task_reconcile_sensor" in SENSORS["status"]
    assert "task_reconcile_sensor" in SENSORS["all"]


def test_all_covers_the_twelve_sensors_once_each():
    assert len(ALL_SENSORS) == len(set(ALL_SENSORS)) == 12
    assert set(ALL_SENSORS) >= {*RUN_STATUS_SENSORS, "task_launcher_sensor", "task_reconcile_sensor"}


def run_command(command, group=None, name=None):
    api = MagicMock()
    calls = []
    api.start_sensor.side_effect = lambda name: calls.append(("start", name)) or "RUNNING"
    api.stop_sensor.side_effect = lambda name: calls.append(("stop", name)) or "STOPPED"
    with patch("fncli.cmds.sensor.DagsterAPI", return_value=api), patch("fncli.cmds.sensor.DagsterConfig"):
        command.callback(group=group, name=name)
    return calls


def test_start_sensor_all_starts_every_sensor():
    calls = run_command(start_sensor_command, group="all")

    assert calls == [("start", name) for name in ALL_SENSORS]


def test_stop_sensor_all_stops_every_sensor():
    calls = run_command(stop_sensor_command, group="all")

    assert calls == [("stop", name) for name in reversed(ALL_SENSORS)]


def test_stopping_a_group_reverses_the_order_of_starting_it():
    assert [n for _, n in run_command(start_sensor_command, group="delivery")] == SENSORS["delivery"]
    assert [n for _, n in run_command(stop_sensor_command, group="delivery")] == SENSORS["delivery"][::-1]


def test_a_sensor_can_be_picked_by_name_and_the_reconcile_sensor_is_one_of_them():
    assert run_command(start_sensor_command, name="task_reconcile_sensor") == [("start", "task_reconcile_sensor")]
    assert run_command(stop_sensor_command, name="task_reconcile_sensor") == [("stop", "task_reconcile_sensor")]


@pytest.mark.parametrize("group,name", [(None, None), ("all", "task_reconcile_sensor")])
def test_exactly_one_of_group_and_name_is_needed(group, name):
    with pytest.raises(click.UsageError):
        run_command(start_sensor_command, group=group, name=name)
