"""`fncli plan` (fncli.cmds.nodefile): what it prints, with the backend and the cluster faked."""

import logging
import os
from dataclasses import replace

import pytest
import yaml
from click.testing import CliRunner

from fncli.cli import cli
from fncli.cmds import nodefile
from fncli.nodefile.diff import BackendState, ProjectState, ResultsState
from fncli.tests.test_nodefile_diff import node_data, synced_state

EMPTY = BackendState([], set(), [], [], [], [])


@pytest.fixture
def run_plan(tmp_path, monkeypatch):
    """Run `fncli plan` on a node file against a faked backend state"""
    monkeypatch.setattr(nodefile, "current_context", lambda: "kind-fn")
    monkeypatch.setattr(nodefile, "build_backend_api", lambda config: None)

    def run(data, state, *args):
        path = tmp_path / "node.yaml"
        path.write_text(yaml.safe_dump(data))
        monkeypatch.setattr(nodefile, "read_state", lambda api: state)
        return CliRunner().invoke(cli, ["plan", "-f", str(path), *args])

    return run


def test_the_plan_starts_with_the_node_and_the_kubectl_context_and_ends_with_a_summary(run_plan):
    result = run_plan(node_data(), EMPTY)

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "Node http://localhost:5000, kubectl context kind-fn"
    assert lines[-1] == "Plan: 8 to create, 2 to check at apply. Nothing is deleted."
    assert "  + secret        trigger-creds" in result.output
    assert "gitea OAuth app sensor" in result.output


def test_a_secret_to_create_lists_where_each_value_comes_from_and_never_a_value(run_plan, monkeypatch):
    monkeypatch.setenv("DS_PASSWORD", "hunter2-do-not-print")
    data = node_data()
    data["secrets"]["dataset-creds"]["values"] = {
        "PASSWORD": {"env": "DS_PASSWORD"}, "OTHER": {"env": "NOT_SET_ANYWHERE"}, "RANDOM": {"generate": {"length": 12}},
    }
    result = run_plan(data, EMPTY)

    assert "      PASSWORD: env DS_PASSWORD, set" in result.output
    assert "      OTHER: env NOT_SET_ANYWHERE, missing" in result.output
    assert "      RANDOM: random, 12 characters, generated" in result.output
    assert "hunter2" not in result.output


def test_a_synced_node_prints_equals_rows_and_no_sources(run_plan):
    result = run_plan(node_data(), synced_state())

    assert "  = secret        dataset-creds" in result.output
    assert "exists, values not compared" in result.output
    assert "env " not in result.output
    assert result.output.splitlines()[-1] == "Plan: 2 to check at apply, 8 unchanged. Nothing is deleted."


def test_changes_show_their_fields_warnings_and_the_other_projects(run_plan):
    state = synced_state()
    state = replace(state, projects=[
        replace(state.projects[0], results=ResultsState("gitea.fn.svc:4000/gitea_admin/results-repo", "old/", "main", True)),
        ProjectState("zeta", True, ["shared"], "shared", [], None),
    ])
    data = node_data()
    data["datasets"][0]["host"] = "new.svc"
    result = run_plan(data, state)

    assert (
        "  ~ project       alpha" in result.output
        and "results.target_dir: old/ -> results/   (earlier tasks will fail)" in result.output
    )
    assert "host: db.svc -> new.svc   (earlier tasks will fail)" in result.output
    assert "      also used by: zeta" in result.output
    assert result.output.splitlines()[-1] == "Plan: 2 to change, 2 to check at apply, 6 unchanged. Nothing is deleted."


def test_a_live_project_without_a_results_repository_asks_and_a_swap_is_blocked(run_plan):
    state = synced_state()
    live = replace(state.projects[0], name="live", results=None)
    swapped = replace(state.projects[0], name="swapped", results=ResultsState("x/y/z", "results", "main", True))
    data = node_data()
    for name in ("live", "swapped"):
        data["projects"].append({**data["projects"][0], "name": name})
    for project in data["projects"][1:]:
        project["repositories"] = {**project["repositories"], "triggers": []}
    result = run_plan(data, replace(state, projects=state.projects + [live, swapped]))

    assert "  ! project       live" in result.output
    assert "disable and enable needed to assign its results repository" in result.output
    assert "  x project       swapped" in result.output
    assert "1 needs a confirmation, 1 blocked" in result.output.splitlines()[-1]


def test_project_limits_the_plan_and_an_unknown_project_is_an_error(run_plan):
    data = node_data()
    result = run_plan(data, EMPTY, "--project", "alpha")
    assert result.exit_code == 0, result.output

    result = run_plan(data, EMPTY, "--project", "nope")
    assert result.exit_code == 1
    assert "Project nope is not in the node file, which has: alpha" in result.output


def test_a_bad_node_file_lists_its_problems(run_plan):
    data = node_data()
    data["projects"][0]["datasets"] = ["shared", "Shared"]
    result = run_plan(data, EMPTY)

    assert result.exit_code == 1
    assert "has 1 problem:" in result.output and "dataset shared is listed twice" in result.output


def test_a_project_dataset_on_the_node_but_not_in_the_file_is_an_existing_reference_and_one_nowhere_is_blocked(run_plan):
    data = node_data()
    del data["datasets"]
    data["projects"][0]["datasets"] = ["shared"]
    present = run_plan(data, synced_state())
    absent = run_plan(data, replace(synced_state(), datasets=[]))

    assert present.exit_code == 0, present.output
    assert "  = dataset       shared" in present.output and "on the node, not in this file" in present.output
    assert absent.exit_code == 0, absent.output
    assert "  x project       alpha" in absent.output and "dataset shared is not in the file or on the node" in absent.output
    assert absent.output.splitlines()[-1] == "Plan: 1 blocked, 2 to check at apply, 6 unchanged. Nothing is deleted."


def test_the_file_comes_from_the_option_or_the_env_never_a_search(run_plan, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cli, ["plan"])
    assert result.exit_code == 2 and "Missing option '-f' / '--file'" in result.output

    path = tmp_path / "node.yaml"
    path.write_text(yaml.safe_dump(node_data()))
    monkeypatch.setattr(nodefile, "current_context", lambda: "kind-fn")
    monkeypatch.setattr(nodefile, "build_backend_api", lambda config: None)
    monkeypatch.setattr(nodefile, "read_state", lambda api: EMPTY)
    monkeypatch.setenv("FNCLI_NODE_FILE", str(path))
    assert CliRunner().invoke(cli, ["plan"]).exit_code == 0


def test_a_file_path_is_also_looked_up_under_bootstrap_from_here_up(tmp_path, monkeypatch):
    plan_file = tmp_path / "bootstrap" / "foo" / "foo-plan.yaml"
    plan_file.parent.mkdir(parents=True)
    plan_file.write_text(yaml.safe_dump(node_data()))
    (tmp_path / "dagster").mkdir()
    monkeypatch.chdir(tmp_path / "dagster")
    monkeypatch.setattr(nodefile, "current_context", lambda: "kind-fn")
    monkeypatch.setattr(nodefile, "build_backend_api", lambda config: None)
    monkeypatch.setattr(nodefile, "read_state", lambda api: EMPTY)

    assert CliRunner().invoke(cli, ["plan", "-f", "foo/foo-plan.yaml"]).exit_code == 0
    result = CliRunner().invoke(cli, ["plan", "-f", "foo/nope.yaml"])
    assert result.exit_code == 2 and "foo/nope.yaml not found, as given or under bootstrap/" in result.output


def test_a_file_for_another_kubectl_context_is_refused(run_plan):
    data = node_data()
    data["node"]["kube_context"] = "client-x"
    result = run_plan(data, EMPTY)

    assert result.exit_code == 1
    assert "is for kubectl context client-x, but the current one is kind-fn" in result.output


def test_the_env_file_is_found_from_the_node_file_up_and_loaded(run_plan, tmp_path, monkeypatch):
    monkeypatch.delenv("FN_TEST_FROM_NODE_ENV", raising=False)
    (tmp_path.parent / "node-test.env").write_text("FN_TEST_FROM_NODE_ENV=yes\n")
    data = node_data()
    data["node"]["env_file"] = "node-test.env"
    assert run_plan(data, EMPTY).exit_code == 0
    assert os.environ["FN_TEST_FROM_NODE_ENV"] == "yes"
    monkeypatch.delenv("FN_TEST_FROM_NODE_ENV")

    data["node"]["env_file"] = "nope.env"
    result = run_plan(data, EMPTY)
    assert result.exit_code == 1 and "node.env_file nope.env not found" in result.output


def test_the_backend_clients_info_logs_stay_out_of_the_plan_and_the_level_is_restored_after(tmp_path, monkeypatch, caplog):
    def noisy_read_state(api):
        logging.getLogger("app.backend").info("Fetching projects")
        return EMPTY

    path = tmp_path / "node.yaml"
    path.write_text(yaml.safe_dump(node_data()))
    monkeypatch.setattr(nodefile, "current_context", lambda: "kind-fn")
    monkeypatch.setattr(nodefile, "build_backend_api", lambda config: None)
    monkeypatch.setattr(nodefile, "read_state", noisy_read_state)
    before = logging.getLogger("app").level

    with caplog.at_level(logging.INFO):
        result = CliRunner().invoke(cli, ["plan", "-f", str(path)])
        assert result.exit_code == 0, result.output
        assert "Fetching projects" not in caplog.text
        logging.getLogger("app.backend").info("after the plan")
        assert "after the plan" in caplog.text

    assert logging.getLogger("app").level == before
