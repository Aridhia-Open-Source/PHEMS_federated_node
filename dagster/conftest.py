"""
Opt-in switch for the end-to-end tests (fncli/tests/e2e), which need a live dev cluster:
they are skipped unless pytest is run with --e2e.
"""

import pytest


def pytest_addoption(parser):
    parser.addoption("--e2e", action="store_true", default=False, help="Run the end-to-end tests against the live dev cluster.")


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end test against the live dev cluster, needs --e2e")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--e2e"):
        return
    skip = pytest.mark.skip(reason="needs a live dev cluster, run with --e2e")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)
