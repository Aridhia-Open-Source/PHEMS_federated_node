from unittest.mock import MagicMock, patch

import dagster as dg
import pytest

from app.config import SENSOR_RETRY_INTERVAL_SECONDS
from app.definitions.sensors import base
from app.definitions.sensors.base import IN_FLIGHT, LaunchingSensor, run_in_flight, run_key


def test_the_run_key_has_kind_item_state_and_slot():
    with patch.object(base.time, "time", return_value=SENSOR_RETRY_INTERVAL_SECONDS * 7 + 1):
        assert run_key("ingest", 3, "cursor") == "ingest/3/cursor/7"
        assert run_key("deliver-retry", 3) == "deliver-retry/3/7"
        assert run_key("sync") == "sync/7"


def test_the_run_key_keeps_a_state_of_zero():
    with patch.object(base.time, "time", return_value=0):
        assert run_key("k", 1, 0) == "k/1/0/0"


def test_the_run_key_changes_with_the_state_at_once_and_with_the_slot_over_time():
    with patch.object(base.time, "time", return_value=100):
        same = run_key("k", 1, "a")
        assert run_key("k", 1, "a") == same
        assert run_key("k", 1, "b") != same
    with patch.object(base.time, "time", return_value=100 + SENSOR_RETRY_INTERVAL_SECONDS):
        assert run_key("k", 1, "a") != same


def test_run_in_flight_filters_on_the_job_tags_and_statuses():
    context = MagicMock()
    context.instance.get_runs.return_value = [MagicMock()]
    job = MagicMock()
    job.name = "my_job"

    assert run_in_flight(context, job, {"a": "1"}) is True

    filters = context.instance.get_runs.call_args.kwargs["filters"]
    assert (filters.job_name, filters.tags, filters.statuses) == ("my_job", {"a": "1"}, IN_FLIGHT)
    context.instance.get_runs.return_value = []
    assert run_in_flight(context, job, {}) is False


class FakeSensor(LaunchingSensor):
    job = MagicMock()
    job.name = "fake_job"
    failure_label = "Fake"
    skip_message = "Nothing to do."

    def __init__(self, context, things, broken=(), ready=None):
        super().__init__(context)
        self.things = things
        self.broken = broken
        self.ready_things = ready if ready is not None else things

    def items(self):
        return self.things

    def describe(self, item):
        return f"thing {item}"

    def tags(self, item):
        return {"thing": str(item)}

    def ready(self, item):
        if item in self.broken:
            raise RuntimeError("boom")
        return item in self.ready_things

    def run_request(self, item):
        return dg.RunRequest(run_key=f"fake/{item}")


def tick(things, in_flight=(), **kwds):
    context = MagicMock()
    context.instance.get_runs.side_effect = lambda filters, limit: (
        [MagicMock()] if filters.tags["thing"] in in_flight else []
    )
    return list(FakeSensor(context, things, **kwds)()), context


def test_a_run_is_requested_per_ready_item():
    results, _ = tick([1, 2, 3], ready=[1, 3])

    assert [r.run_key for r in results] == ["fake/1", "fake/3"]


def test_an_item_in_flight_is_skipped_without_the_ready_check():
    results, _ = tick([1, 2], in_flight={"1"}, broken=[1])

    assert [r.run_key for r in results] == ["fake/2"]


def test_it_skips_when_nothing_is_ready_and_nothing_failed():
    results, _ = tick([1], ready=[])

    assert len(results) == 1 and results[0].skip_message == "Nothing to do."


def test_a_failing_item_does_not_stop_the_others():
    results, _ = tick([1, 2, 3], broken=[2])

    assert [r.run_key for r in results] == ["fake/1", "fake/3"]


def test_the_tick_fails_naming_the_items_when_nothing_launched():
    with pytest.raises(RuntimeError, match="Fake failed for thing 1, thing 2"):
        tick([1, 2], broken=[1, 2])
