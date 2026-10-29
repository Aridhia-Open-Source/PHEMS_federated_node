"""
The Dagster-side enums must carry the same values as nexus-api's, which defines them.

The two packages are both called `app`, so the nexus-api source is parsed with `ast` rather than imported. It
lives outside dagster/, so the test image gets it as a read-only mount (docker-compose-tests-ci.yaml) and a
checkout has it beside dagster/:

    pytest dagster/app/tests/test_enum_drift.py
"""

import ast
from pathlib import Path

import pytest

from app.models import PullRequestResultStep, ResultState, TaskStatus, TriggerState

NEXUS_MODELS = Path(__file__).resolve().parents[3] / "nexus" / "api" / "app" / "models"


def nexus_members(filename: str, class_name: str) -> dict[str, str]:
    """The NAME = "value" members of a class in a nexus-api models module."""
    tree = ast.parse((NEXUS_MODELS / filename).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return {
        stmt.targets[0].id: stmt.value.value
        for stmt in cls.body
        if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name)
        and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)
    }


@pytest.mark.parametrize("enum,filename", [
    (TaskStatus, "task_status.py"),
    (TriggerState, "trigger_state.py"),
    (ResultState, "result_state.py"),
    (PullRequestResultStep, "pull_request_result_step.py"),
])
def test_the_dagster_enum_has_the_values_of_the_nexus_enum(enum, filename):
    expected = nexus_members(filename, enum.__name__)

    assert expected, f"no members found for {enum.__name__} in nexus-api"
    assert {m.name: m.value for m in enum} == expected
