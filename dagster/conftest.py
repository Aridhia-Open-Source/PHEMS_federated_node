"""
Switch for the end-to-end tests (fncli/tests/e2e), which need a live dev cluster. Run from the repo
root, where fncli finds .dev.env, with the option after the paths (`--e2e` takes an optional value):

    pytest dagster --e2e -v            # every e2e test: the happy path, then the failure paths
    pytest dagster --e2e success -v    # only the happy path
    pytest dagster --e2e failure -v    # only the failure paths
    pytest dagster --e2e failure2 -v   # only the failure paths that switch something off or revoke it

A plain `pytest` skips them all.
"""

import pytest

E2E_SUITES = ["all", "success", "failure", "failure2"]


def pytest_addoption(parser):
    parser.addoption(
        "--e2e",
        nargs="?",
        const="all",
        default=None,
        choices=E2E_SUITES,
        help="Run only the end-to-end tests, against the live dev cluster: all (the default), success, failure or failure2.",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end test against the live dev cluster, run with --e2e")
    config.addinivalue_line("markers", "e2e_success: the end-to-end happy path, run with --e2e success")
    config.addinivalue_line("markers", "e2e_failure: the end-to-end failure paths, run with --e2e failure")
    config.addinivalue_line("markers", "e2e_failure2: the end-to-end failure paths that switch something off, run with --e2e failure2")
    if config.getoption("--e2e"):
        # Each step depends on the one before, so stop at the first failure, and show progress as it happens
        config.option.maxfail = 1
        config.option.log_cli_level = "INFO"
        config.option.log_cli_format = "%(asctime)s %(levelname)-8s %(name)s:%(filename)s:%(lineno)d %(message)s"
        config.option.log_cli_date_format = "%H:%M:%S"
        # Every step's time at the end, to see where a run spends it (the same as --durations=0)
        config.option.durations = 0


def pytest_collection_modifyitems(config, items):
    suite = config.getoption("--e2e")
    if suite:
        wanted = "e2e" if suite == "all" else f"e2e_{suite}"
        selected = [item for item in items if wanted in item.keywords]
        config.hook.pytest_deselected(items=[item for item in items if wanted not in item.keywords])
        # The happy path first, then the failure paths, then the ones that switch something off (the sort is stable)
        order = ["e2e_success", "e2e_failure", "e2e_failure2"]
        selected.sort(key=lambda item: next((i for i, name in enumerate(order) if name in item.keywords), 0))
        items[:] = selected
        return
    skip = pytest.mark.skip(reason="needs a live dev cluster, run with --e2e")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)
