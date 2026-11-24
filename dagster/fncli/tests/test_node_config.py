import json
from types import SimpleNamespace

import click
import pytest

from fncli import node_config


def resource(generation, observed, synced=True, kind="Project", name="fn-dev"):
    return {
        "apiVersion": node_config.GROUP_VERSION, "kind": kind,
        "metadata": {"name": name, "generation": generation},
        "status": {"synced": synced, "observedGeneration": observed, "message": "waiting for dataset x"},
    }


@pytest.fixture
def kubectl_get(monkeypatch):
    """Each kubectl get returns the next list of items"""
    answers = []
    monkeypatch.setattr(node_config.time, "sleep", lambda _: None)

    def run(args, **_):
        items = answers.pop(0) if len(answers) > 1 else answers[0]
        return SimpleNamespace(returncode=0, stdout=json.dumps({"items": items}))

    monkeypatch.setattr(node_config.subprocess, "run", run)
    return answers


def test_synced_needs_the_current_generation():
    assert node_config.synced(resource(2, 2))
    assert not node_config.synced(resource(2, 1))
    assert not node_config.synced(resource(2, 2, synced=False))
    assert not node_config.synced({"metadata": {"generation": 1}})


def test_wait_synced_waits_for_a_reapplied_resource_to_catch_up(kubectl_get):
    kubectl_get.extend([[resource(2, 1)], [resource(2, 1)], [resource(2, 2)]])

    node_config.wait_synced("-f", "config/e2e/fn-dev.yaml")

    assert len(kubectl_get) == 1


def test_wait_synced_ignores_other_kinds_in_the_files(kubectl_get):
    secret = {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "creds"}}
    kubectl_get.append([secret, resource(1, 1)])

    node_config.wait_synced("-f", "config/demo.yaml")


def test_wait_synced_times_out_naming_what_is_not_synced(kubectl_get, monkeypatch):
    kubectl_get.append([resource(2, 1)])
    clock = iter([0, 0, node_config.SYNC_TIMEOUT_SECONDS + 1])
    monkeypatch.setattr(node_config.time, "monotonic", lambda: next(clock))

    with pytest.raises(click.ClickException, match="Project/fn-dev \\(waiting for dataset x\\)"):
        node_config.wait_synced("-f", "config/e2e/fn-dev.yaml")
