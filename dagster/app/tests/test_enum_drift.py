"""
The Dagster-side enums must carry the same values as the webserver's, which defines them.

The two packages are both called `app`, so the webserver source is parsed with `ast` rather than imported. It needs
the whole repository, so run it from a checkout, from the repository root:

    pytest dagster/app/tests/test_enum_drift.py

The Dagster test image holds only dagster/, where this module is skipped.
"""

import ast
from pathlib import Path

import pytest

from app.models import PullRequestResultStep, ResultState, TaskStatus, TriggerState

WEBSERVER_MODELS = Path(__file__).resolve().parents[3] / "webserver" / "app" / "models"

pytestmark = pytest.mark.skipif(
    not WEBSERVER_MODELS.is_dir(), reason="the webserver source is not next to dagster/ (run from a full checkout)"
)


def webserver_members(filename: str, class_name: str) -> dict[str, str]:
    """The NAME = "value" members of a class in a webserver models module."""
    tree = ast.parse((WEBSERVER_MODELS / filename).read_text())
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
def test_the_dagster_enum_has_the_values_of_the_webserver_enum(enum, filename):
    expected = webserver_members(filename, enum.__name__)

    assert expected, f"no members found for {enum.__name__} in the webserver"
    assert {m.name: m.value for m in enum} == expected
