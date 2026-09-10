"""
Tests for the database liveness script.
"""
import importlib
import sys
import types
from unittest import mock

import pytest


class _StubConnectionError(Exception):
    pass


def _install_pyodbc_stub(monkeypatch, fail_times):
    """Fake pyodbc whose connect() fails the first `fail_times` calls."""
    calls = {"count": 0}

    def connect(_connection_string, timeout=None):
        if calls["count"] < fail_times:
            calls["count"] += 1
            raise _StubConnectionError(
                "('40613', 'Database is not currently available, resuming')"
            )
        calls["count"] += 1

        cursor = mock.Mock()
        connection = mock.Mock()
        connection.cursor.return_value = cursor
        return connection

    stub = types.ModuleType("pyodbc")
    stub.connect = connect
    monkeypatch.setitem(sys.modules, "pyodbc", stub)
    return calls


def _load_liveness(monkeypatch, env):
    for key in ("DB_LIVENESS_RETRIES", "DB_LIVENESS_BACKOFF", "DB_LIVENESS_TIMEOUT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CONNECTION_STRING", "driver=stub;Server=db")
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    sys.modules.pop("liveness", None)
    return importlib.import_module("liveness")


def test_succeeds_on_first_attempt(monkeypatch):
    _install_pyodbc_stub(monkeypatch, fail_times=0)
    liveness = _load_liveness(monkeypatch, {"DB_LIVENESS_RETRIES": 5, "DB_LIVENESS_BACKOFF": 30})
    with mock.patch("time.sleep") as sleep:
        assert liveness.check() == 0
        sleep.assert_not_called()


def test_recovers_while_db_resumes(monkeypatch):
    # Two failures (DB resuming), then a connection on the third try.
    _install_pyodbc_stub(monkeypatch, fail_times=2)
    liveness = _load_liveness(monkeypatch, {"DB_LIVENESS_RETRIES": 5, "DB_LIVENESS_BACKOFF": 30})
    with mock.patch("time.sleep") as sleep:
        assert liveness.check() == 0
        # Gap grows by the increment each round: 30s, then 60s.
        assert [c.args[0] for c in sleep.call_args_list] == [30, 60]


def test_fails_after_all_retries(monkeypatch):
    _install_pyodbc_stub(monkeypatch, fail_times=99)
    liveness = _load_liveness(monkeypatch, {"DB_LIVENESS_RETRIES": 3, "DB_LIVENESS_BACKOFF": 10})
    with mock.patch("time.sleep") as sleep:
        assert liveness.check() == 1
        # 3 attempts means 2 waits: 10s and 20s.
        assert [c.args[0] for c in sleep.call_args_list] == [10, 20]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
