from fncli.cmds.sensor import ALL_SENSORS, RUN_STATUS_SENSORS, SENSORS


def test_the_delivery_sensor_is_selectable_and_in_all():
    assert SENSORS["delivery"] == ["task_results_delivery_sensor"]
    assert "task_results_delivery_sensor" in SENSORS["all"]


def test_run_status_sensors_start_before_the_launcher():
    launcher = ALL_SENSORS.index("task_launcher_sensor")

    for name in [*RUN_STATUS_SENSORS, "task_results_delivery_sensor"]:
        assert ALL_SENSORS.index(name) < launcher
