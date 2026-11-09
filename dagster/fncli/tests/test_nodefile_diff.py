"""The pure diff of a node file against a backend snapshot (fncli.nodefile.diff), with no cluster."""

import copy
from dataclasses import replace
from pathlib import Path

import pytest

from fncli.nodefile.diff import (
    BLOCKED, CONFIRM, CREATE, ENSURE, EARLIER_TASKS_FAIL, UNCHANGED, UPDATE, BackendState, DatasetState, ProjectState,
    ProviderState, RepositoryState, ResultsState, TriggerState, count, diff,
)
from fncli.nodefile.loader import limit_to_project, load_node_file
from fncli.nodefile.schema import NodeFile

ROOT = Path(__file__).parents[3]
TRIGGER = "http://gitea.fn.svc:4000/gitea_admin/trigger-repo"
RESULTS = "http://gitea.fn.svc:4000/gitea_admin/results-repo"
TRIGGER_N = "gitea.fn.svc:4000/gitea_admin/trigger-repo"
RESULTS_N = "gitea.fn.svc:4000/gitea_admin/results-repo"
PROVIDER = "http://gitea.fn.svc:4000"


def node_data() -> dict:
    return {
        "version": 1,
        "node": {"url": "http://localhost:5000", "kube_context": "kind-fn", "keycloak_namespace": "keycloak"},
        "providers": [{"name": "gitea-local", "type": "gitea", "uri": PROVIDER, "api_uri": f"{PROVIDER}/api/v1"}],
        "secrets": {
            "trigger-creds": {"gitea_oauth": {"app": "sensor"}},
            "results-creds": {"gitea_oauth": {"app": "results"}},
            "dataset-creds": {"values": {"USERNAME": {"generate": {}}}},
        },
        "repositories": {
            "triggers": [{"uri": TRIGGER, "secret": "trigger-creds"}],
            "results": [{"uri": RESULTS, "secret": "results-creds"}],
        },
        "datasets": [{
            "name": "Shared", "type": "postgres", "host": "db.svc", "port": 5432,
            "read_schema": "cdm", "write_schema": "results", "secret": "dataset-creds",
        }],
        "projects": [{
            "name": "alpha",
            "datasets": ["shared"],
            "repositories": {
                "triggers": [{"repository": TRIGGER, "watch_dir": "specs/", "base_branch": "main"}],
                "results": {"repository": RESULTS, "target_dir": "results/", "base_branch": "main"},
            },
        }],
        "gitea": {"provider": "gitea-local", "create_repositories": True},
    }


def make_node(data=None) -> NodeFile:
    return NodeFile.model_validate(data or node_data())


def synced_state() -> BackendState:
    """What the backend holds when the file above has been applied, in the backend's own forms"""
    return BackendState(
        providers=[ProviderState("gitea-local", "gitea", PROVIDER, f"{PROVIDER}/api/v1")],
        secrets={"trigger-creds", "results-creds", "dataset-creds"},
        trigger_repositories=[RepositoryState(TRIGGER_N, PROVIDER, "trigger-creds")],
        results_repositories=[RepositoryState(RESULTS_N, PROVIDER, "results-creds")],
        datasets=[DatasetState("shared", "postgres", "db.svc", 5432, "cdm", "results", "dataset-creds")],
        projects=[ProjectState(
            "alpha", True, ["shared"], "shared",
            [TriggerState(TRIGGER_N, "specs", "main", True)],
            ResultsState(RESULTS_N, "results", "main", True),
        )],
    )


def by(changes, kind, name=None):
    found = [c for c in changes if c.kind == kind and (name is None or c.name == name)]
    assert found, f"no {kind} {name} in {[(c.kind, c.name) for c in changes]}"
    return found if name is None else found[0]


def test_a_synced_node_has_nothing_to_change():
    changes = diff(make_node(), synced_state())
    assert {c.action for c in changes} == {UNCHANGED, ENSURE}
    assert all(not c.fields and not c.warnings for c in changes)
    assert count(changes)[UNCHANGED] == 8


def test_an_empty_backend_creates_everything_in_dependency_order():
    empty = BackendState([], set(), [], [], [], [])
    changes = diff(make_node(), empty)
    assert [(c.action, c.kind) for c in changes] == [
        (ENSURE, "gitea repo"), (ENSURE, "gitea repo"),
        (CREATE, "secret"), (CREATE, "secret"), (CREATE, "secret"),
        (CREATE, "provider"), (CREATE, "trigger repo"), (CREATE, "results repo"),
        (CREATE, "dataset"), (CREATE, "project"),
    ]
    assert by(changes, "secret", "trigger-creds").detail == "gitea OAuth app sensor"
    assert by(changes, "secret", "dataset-creds").detail == "values USERNAME"
    assert by(changes, "project", "alpha").detail == "1 datasets, 1 triggers, results gitea_admin/results-repo"
    assert by(changes, "gitea repo")[0].name == "gitea_admin/trigger-repo"


def test_gitea_repositories_are_only_listed_when_the_file_asks_and_are_on_the_gitea_provider():
    data = node_data()
    data["providers"].append({"type": "github", "uri": "https://github.com"})
    data["repositories"]["triggers"].append({"uri": "https://github.com/org/repo", "secret": "trigger-creds"})
    names = [c.name for c in diff(make_node(data), synced_state()) if c.kind == "gitea repo"]
    assert names == ["gitea_admin/trigger-repo", "gitea_admin/results-repo"]
    data["gitea"]["create_repositories"] = False
    assert not [c for c in diff(make_node(data), synced_state()) if c.kind == "gitea repo"]
    del data["gitea"]
    data["secrets"]["trigger-creds"] = {"values": {"A": {"env": "X"}}}
    data["secrets"]["results-creds"] = {"values": {"A": {"env": "X"}}}
    assert not [c for c in diff(make_node(data), synced_state()) if c.kind == "gitea repo"]


def test_an_existing_secret_is_unchanged_whatever_its_sources():
    secret = by(diff(make_node(), synced_state()), "secret", "dataset-creds")
    assert (secret.action, secret.detail) == (UNCHANGED, "exists, values not compared")


def test_a_provider_name_is_compared_only_when_the_file_gives_one():
    state = synced_state()
    state = replace(state, providers=[replace(state.providers[0], name="renamed", api_uri=f"{PROVIDER}/api/v1/")])
    provider = by(diff(make_node(), state), "provider")[0]
    assert provider.action == UPDATE
    assert [str(f) for f in provider.fields] == ["name: renamed -> gitea-local"]
    data = node_data()
    del data["providers"][0]["name"]
    del data["gitea"]
    data["secrets"]["trigger-creds"] = data["secrets"]["results-creds"] = {"values": {"A": {"env": "X"}}}
    assert by(diff(make_node(data), state), "provider")[0].action == UNCHANGED


def test_a_repository_secret_change_lists_the_other_projects_assigned_to_it():
    state = synced_state()
    state = replace(
        state,
        trigger_repositories=[RepositoryState(TRIGGER_N, PROVIDER, "old-creds")],
        projects=state.projects + [
            ProjectState("zeta", True, [], None, [TriggerState(TRIGGER_N, "x", "main", True)], None),
            ProjectState("omega", True, [], None, [], None),
        ],
    )
    repo = by(diff(make_node(), state), "trigger repo")[0]
    assert repo.action == UPDATE
    assert [str(f) for f in repo.fields] == ["secret: old-creds -> trigger-creds"]
    assert repo.also_used_by == ("zeta",)


def test_a_repository_on_another_provider_is_a_change_of_its_provider():
    state = synced_state()
    state = replace(state, results_repositories=[RepositoryState(RESULTS_N, "http://old.example", "results-creds")])
    repo = by(diff(make_node(), state), "results repo")[0]
    assert [str(f) for f in repo.fields] == ["provider: http://old.example -> http://gitea.fn.svc:4000"]


@pytest.mark.parametrize("field,value", [("host", "other.svc"), ("port", 6543), ("type", "mysql"), ("read_schema", None)])
def test_a_dataset_change_that_is_pinned_into_tasks_is_flagged_and_lists_the_other_projects(field, value):
    state = synced_state()
    state = replace(
        state,
        datasets=[replace(state.datasets[0], **{field: value})],
        projects=state.projects + [ProjectState("zeta", True, ["SHARED"], "SHARED", [], None)],
    )
    dataset = by(diff(make_node(), state), "dataset", "Shared")
    assert dataset.action == UPDATE
    assert dataset.warnings == (EARLIER_TASKS_FAIL,)
    assert dataset.also_used_by == ("zeta",)


def test_a_dataset_secret_change_is_not_flagged_and_names_compare_in_lowercase():
    state = synced_state()
    state = replace(state, datasets=[replace(state.datasets[0], name="SHARED", secret="old")])
    dataset = by(diff(make_node(), state), "dataset", "Shared")
    assert (dataset.action, dataset.warnings, [str(f) for f in dataset.fields]) == (
        UPDATE, (), ["secret: old -> dataset-creds"],
    )


def test_an_unset_schema_and_an_empty_one_are_the_same():
    state = synced_state()
    state = replace(state, datasets=[replace(state.datasets[0], read_schema="")])
    data = node_data()
    del data["datasets"][0]["read_schema"]
    assert by(diff(make_node(data), state), "dataset", "Shared").action == UNCHANGED


def test_the_projects_in_the_file_are_not_listed_as_other_projects():
    state = synced_state()
    state = replace(state, datasets=[replace(state.datasets[0], host="other.svc")])
    assert by(diff(make_node(), state), "dataset", "Shared").also_used_by == ()


def test_a_results_target_dir_or_base_branch_change_is_flagged():
    state = synced_state()
    state = replace(state, projects=[replace(state.projects[0], results=ResultsState(RESULTS_N, "old/", "dev", True))])
    project = by(diff(make_node(), state), "project", "alpha")
    assert project.action == UPDATE
    assert [str(f) for f in project.fields] == [
        "results.target_dir: old/ -> results/", "results.base_branch: dev -> main",
    ]
    assert project.warnings == (EARLIER_TASKS_FAIL,)


def test_a_trigger_change_applies_at_once_and_is_not_flagged():
    state = synced_state()
    trigger = TriggerState(TRIGGER_N, "old", "dev", False)
    state = replace(state, projects=[replace(state.projects[0], triggers=[trigger])])
    project = by(diff(make_node(), state), "project", "alpha")
    assert [str(f) for f in project.fields] == [
        "triggers[trigger-repo].watch_dir: old -> specs/",
        "triggers[trigger-repo].base_branch: dev -> main",
        "triggers[trigger-repo].enabled: false -> true",
    ]
    assert project.warnings == ()


def test_directories_that_differ_only_in_slashes_are_the_same():
    state = synced_state()
    trigger = TriggerState(TRIGGER_N, "/specs//", "main", True)
    results = ResultsState(RESULTS_N, "./results", "main", True)
    state = replace(state, projects=[replace(state.projects[0], triggers=[trigger], results=results)])
    assert by(diff(make_node(), state), "project", "alpha").action == UNCHANGED


def test_a_project_that_is_disabled_in_the_backend_is_enabled_by_the_file():
    state = synced_state()
    state = replace(state, projects=[replace(state.projects[0], enabled=False)])
    project = by(diff(make_node(), state), "project", "alpha")
    assert [str(f) for f in project.fields] == ["enabled: false -> true"]


def test_missing_assignments_on_an_existing_project():
    state = synced_state()
    state = replace(state, projects=[replace(state.projects[0], datasets=[], default_dataset=None, triggers=[], enabled=False,
                                             results=None)])
    project = by(diff(make_node(), state), "project", "alpha")
    assert project.action == UPDATE
    assert [str(f) for f in project.fields] == [
        "enabled: false -> true",
        "datasets: + shared",
        "triggers: + gitea_admin/trigger-repo (watch_dir specs/, base_branch main)",
        "results: + gitea_admin/results-repo (target_dir results/, base_branch main)",
    ]


def test_assigning_a_results_repository_to_a_live_project_needs_a_confirmation():
    state = synced_state()
    state = replace(state, projects=[replace(state.projects[0], results=None)])
    changes = [c for c in diff(make_node(), state) if c.kind == "project"]
    assert [(c.action, c.name) for c in changes] == [(CONFIRM, "alpha")]
    assert changes[0].detail == "disable and enable needed to assign its results repository"
    assert changes[0].warnings == ("pull requests merged meanwhile get no trigger",)
    assert [str(f) for f in changes[0].fields] == [
        "results: + gitea_admin/results-repo (target_dir results/, base_branch main)"
    ]


def test_swapping_the_results_repository_is_blocked():
    state = synced_state()
    state = replace(state, projects=[replace(state.projects[0], results=ResultsState("x/y/z", "results", "main", True))])
    changes = [c for c in diff(make_node(), state) if c.kind == "project"]
    assert [(c.action, c.name) for c in changes] == [(BLOCKED, "alpha")]
    assert "the backend refuses a swap" in changes[0].detail and "y/z" in changes[0].detail


def test_a_different_default_dataset_is_blocked_because_the_backend_cannot_change_it():
    state = synced_state()
    state = replace(state, projects=[replace(state.projects[0], default_dataset="other", datasets=["other", "shared"])])
    changes = [c for c in diff(make_node(), state) if c.kind == "project"]
    assert [(c.action, c.name) for c in changes] == [(BLOCKED, "alpha")]
    assert "default dataset is other but the file lists shared first" in changes[0].detail


def test_other_changes_of_a_project_are_kept_beside_a_blocked_one():
    state = synced_state()
    project = replace(state.projects[0], results=ResultsState("x/y/z", "results", "main", True), enabled=False)
    state = replace(state, projects=[project])
    assert [c.action for c in diff(make_node(), state) if c.kind == "project"] == [UPDATE, BLOCKED]


def test_limiting_to_a_project_keeps_the_others_as_other_projects():
    data = node_data()
    beta = copy.deepcopy(data["projects"][0])
    beta["name"] = "beta"
    beta["repositories"]["triggers"] = []
    beta["repositories"]["results"]["target_dir"] = "beta-results/"
    data["projects"].append(beta)
    state = synced_state()
    state = replace(
        state,
        datasets=[replace(state.datasets[0], host="other.svc")],
        projects=state.projects + [replace(state.projects[0], name="beta")],
    )
    node = limit_to_project(make_node(data), "alpha")
    changes = diff(node, state)
    assert not [c for c in changes if c.name == "beta"]
    assert by(changes, "dataset", "Shared").also_used_by == ("beta",)


@pytest.mark.skipif(not (ROOT / "bootstrap" / "examples" / "demo-gitea.yaml").exists(), reason="the repo's bootstrap/examples files are not in the test image")
def test_the_gitea_demo_against_what_the_env_setup_creates_differs_only_in_the_providers_name():
    """
    Backend-style values as `setup-project` leaves them from .demo.env: normalised uris, no trailing slashes, and the
    provider named <type>-<host> by init_backend_provider. The file names it gitea-local, which the gitea section refers to.
    """
    node = load_node_file(ROOT / "bootstrap" / "examples" / "demo-gitea.yaml")
    trigger, results = "gitea.fn.svc:4000/gitea_admin/demo-trigger-repo", "gitea.fn.svc:4000/gitea_admin/demo-results-repo"
    state = BackendState(
        providers=[ProviderState("gitea-gitea.fn.svc:4000", "gitea", PROVIDER, f"{PROVIDER}/api/v1")],
        secrets={"demo-trigger-repo-creds", "demo-results-repo-creds", "demo-dataset-dataset-creds"},
        trigger_repositories=[RepositoryState(trigger, PROVIDER, "demo-trigger-repo-creds")],
        results_repositories=[RepositoryState(results, PROVIDER, "demo-results-repo-creds")],
        datasets=[DatasetState("demo-dataset", "postgres", "db-datasets.experiments.svc", 5432, "cdm", "results",
                               "demo-dataset-dataset-creds")],
        projects=[ProjectState(
            "demo-gitea", True, ["demo-dataset"], "demo-dataset",
            [TriggerState(trigger, "specs", "main", True)], ResultsState(results, "results", "main", True),
        )],
    )
    changed = [c for c in diff(node, state) if c.action not in (UNCHANGED, ENSURE)]
    assert [(c.kind, c.action, [str(f) for f in c.fields]) for c in changed] == [
        ("provider", UPDATE, ["name: gitea-gitea.fn.svc:4000 -> gitea-local"]),
    ]


@pytest.mark.skipif(not (ROOT / "bootstrap" / "examples" / "demo-github.yaml").exists(), reason="the repo's bootstrap/examples files are not in the test image")
def test_the_github_demo_against_what_the_env_setup_creates_is_all_unchanged():
    """One repo is both the trigger and the results repository, and the provider has the env setup's default name"""
    node = load_node_file(ROOT / "bootstrap" / "examples" / "demo-github.yaml")
    repo, provider = "github.com/aridhia-open-source/phems-sandbox", "https://github.com"
    state = BackendState(
        providers=[ProviderState("github-github.com", "github", provider, "https://api.github.com")],
        secrets={"phems-sandbox-creds", "demo-github-dataset-dataset-creds"},
        trigger_repositories=[RepositoryState(repo, provider, "phems-sandbox-creds")],
        results_repositories=[RepositoryState(repo, provider, "phems-sandbox-creds")],
        datasets=[DatasetState("demo-github-dataset", "postgres", "db-datasets.experiments.svc", 5432, "cdm", "results",
                               "demo-github-dataset-dataset-creds")],
        projects=[ProjectState(
            "demo-github", True, ["demo-github-dataset"], "demo-github-dataset",
            [TriggerState(repo, "mgmt/requests", "main", True)], ResultsState(repo, "mgmt/results", "main", True),
        )],
    )
    assert {c.action for c in diff(node, state)} == {UNCHANGED}
