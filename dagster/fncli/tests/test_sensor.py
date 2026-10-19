from unittest.mock import MagicMock, patch

from fncli.cmds.sensor import ALL_SENSORS, RUN_STATUS_SENSORS, SENSORS, start_sensor_command, stop_sensor_command


def test_the_delivery_sensors_are_selectable_and_in_all():
    assert SENSORS["delivery"] == [
        "task_results_delivery_sensor", "results_pull_request_sync_sensor", "results_delivery_retry_sensor"
    ]
    assert "task_results_delivery_sensor" in SENSORS["all"]
    assert "results_pull_request_sync_sensor" in SENSORS["all"]
    assert "results_delivery_retry_sensor" in SENSORS["all"]


def test_run_status_sensors_start_before_the_launcher():
    launcher = ALL_SENSORS.index("task_launcher_sensor")

    for name in [*RUN_STATUS_SENSORS, "task_results_delivery_sensor"]:
        assert ALL_SENSORS.index(name) < launcher


def test_all_starts_the_run_status_and_delivery_sensors_first_and_the_launcher_last():
    assert ALL_SENSORS == [
        *RUN_STATUS_SENSORS,
        "task_results_delivery_sensor",
        "results_pull_request_sync_sensor",
        "results_delivery_retry_sensor",
        "git_pull_request_ingest_sensor",
        "git_pull_request_evaluate_sensor",
        "task_launcher_sensor",
    ]
    assert ALL_SENSORS.index("git_pull_request_ingest_sensor") < ALL_SENSORS.index("git_pull_request_evaluate_sensor")


def test_all_covers_the_eleven_sensors_once_each():
    assert len(ALL_SENSORS) == len(set(ALL_SENSORS)) == 11


def run_command(command, sensor):
    api = MagicMock()
    calls = []
    api.start_sensor.side_effect = lambda name: calls.append(("start", name)) or "RUNNING"
    api.stop_sensor.side_effect = lambda name: calls.append(("stop", name)) or "STOPPED"
    with patch("fncli.cmds.sensor.DagsterAPI", return_value=api), patch("fncli.cmds.sensor.DagsterConfig"):
        command.callback(sensor=sensor)
    return calls


def test_start_sensor_all_starts_them_in_order_with_the_launcher_last():
    calls = run_command(start_sensor_command, "all")

    assert calls == [("start", name) for name in ALL_SENSORS]
    assert calls[-1] == ("start", "task_launcher_sensor")


def test_stop_sensor_all_stops_them_in_the_reverse_order_with_the_launcher_first():
    calls = run_command(stop_sensor_command, "all")

    assert calls == [("stop", name) for name in reversed(ALL_SENSORS)]
    assert calls[0] == ("stop", "task_launcher_sensor")


def test_stopping_a_group_reverses_the_order_of_starting_it():
    assert [n for _, n in run_command(start_sensor_command, "delivery")] == SENSORS["delivery"]
    assert [n for _, n in run_command(stop_sensor_command, "delivery")] == SENSORS["delivery"][::-1]
