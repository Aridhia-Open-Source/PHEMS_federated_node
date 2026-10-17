"""
Switch for the end-to-end tests (fncli/tests/e2e), which need a live dev cluster: `pytest --e2e`
runs only them, and a plain `pytest` skips them.
"""

import pytest


def pytest_addoption(parser):
    parser.addoption("--e2e", action="store_true", default=False, help="Run only the end-to-end tests, against the live dev cluster.")


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end test against the live dev cluster, run with --e2e")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--e2e"):
        e2e = [item for item in items if "e2e" in item.keywords]
        config.hook.pytest_deselected(items=[item for item in items if "e2e" not in item.keywords])
        items[:] = e2e
        return
    skip = pytest.mark.skip(reason="needs a live dev cluster, run with --e2e")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)
