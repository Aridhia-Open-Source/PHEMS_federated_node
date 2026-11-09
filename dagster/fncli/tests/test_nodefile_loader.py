"""The node file's schema and loader (fncli.nodefile.schema, fncli.nodefile.loader), with no cluster."""

import copy
from pathlib import Path

import click
import pytest
import yaml
from kubernetes.client.exceptions import ApiException

from fncli.nodefile import loader
from fncli.nodefile.loader import (
    GENERATED, MISSING, SET, check_gitea_owners, check_sources, limit_to_project, load_context, load_node_file,
)
from fncli.nodefile.schema import NodeFile, dirs_overlap, normalise_dir

ADMIN = "gitea_admin"
ROOT = Path(__file__).parents[3]
TRIGGER = "http://gitea.fn.svc:4000/gitea_admin/trigger-repo"
RESULTS = "http://gitea.fn.svc:4000/gitea_admin/results-repo"


def node_data() -> dict:
    return {
        "version": 1,
        "providers": [{
            "name": "gitea-local", "type": "gitea",
            "uri": "http://gitea.fn.svc:4000", "api_uri": "http://gitea.fn.svc:4000/api/v1",
        }],
        "secrets": {
            "trigger-creds": {"gitea_oauth": {"app": "sensor"}},
            "results-creds": {"gitea_oauth": {"app": "results"}},
            "dataset-creds": {"values": {"USERNAME": {"generate": {}}, "PASSWORD": {"env": "DS_PASSWORD"}}},
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


def write(tmp_path, data) -> Path:
    path = tmp_path / "node.yaml"
    path.write_text(data if isinstance(data, str) else yaml.safe_dump(data))
    return path


def load(tmp_path, data) -> NodeFile:
    return load_node_file(write(tmp_path, data))


def problems_of(tmp_path, data) -> str:
    with pytest.raises(click.ClickException) as error:
        load(tmp_path, data)
    return error.value.message


def test_valid_file_loads_with_normalised_uris(tmp_path):
    data = node_data()
    data["repositories"]["triggers"][0]["uri"] = TRIGGER.upper().replace("HTTP", "http") + ".git"
    node = load(tmp_path, data)
    assert node.repositories.triggers[0].uri == "gitea.fn.svc:4000/gitea_admin/trigger-repo"
    assert node.projects[0].repositories.results.enabled is True


def test_github_provider_defaults_its_api_and_name(tmp_path):
    data = node_data()
    data["providers"].append({"type": "github", "uri": "https://github.com/"})
    provider = load(tmp_path, data).providers[1]
    assert (provider.uri, provider.api_uri, provider.resolved_name) == (
        "https://github.com", "https://api.github.com", "github-github.com",
    )


def test_gitea_provider_needs_its_api_uri(tmp_path):
    data = node_data()
    del data["providers"][0]["api_uri"]
    assert "a gitea provider needs an api_uri" in problems_of(tmp_path, data)


def test_api_uri_must_be_on_the_providers_host(tmp_path):
    data = node_data()
    data["providers"][0]["api_uri"] = "http://elsewhere.example/api/v1"
    assert "must be on the host gitea.fn.svc:4000" in problems_of(tmp_path, data)


def test_version_is_required_and_unknown_keys_refused(tmp_path):
    data = node_data()
    del data["version"]
    data["projectz"] = []
    message = problems_of(tmp_path, data)
    assert "version: Field required" in message
    assert "projectz: Extra inputs are not permitted" in message


def test_bare_string_where_a_reference_belongs_is_refused_and_not_echoed(tmp_path):
    data = node_data()
    data["secrets"]["dataset-creds"]["values"]["PASSWORD"] = "hunter2-not-a-reference"
    message = problems_of(tmp_path, data)
    assert "secrets.dataset-creds.values.PASSWORD: a secret value is never written in the file" in message
    assert "hunter2" not in message


def test_a_reference_with_two_kinds_is_refused(tmp_path):
    data = node_data()
    data["secrets"]["dataset-creds"]["values"]["PASSWORD"] = {"env": "A", "file": "b"}
    assert "never written in the file" in problems_of(tmp_path, data)


def test_a_secret_is_values_or_gitea_oauth_not_both_or_neither(tmp_path):
    data = node_data()
    data["secrets"]["trigger-creds"]["values"] = {"A": {"env": "X"}}
    data["secrets"]["results-creds"] = {}
    message = problems_of(tmp_path, data)
    assert message.count("a secret has exactly one of values and gitea_oauth") == 2


def test_all_problems_are_listed_at_once(tmp_path):
    data = node_data()
    data["repositories"]["results"][0]["uri"] = "http://unknown.example/gitea_admin/results-repo"
    data["repositories"]["triggers"].append(data["repositories"]["triggers"][0])
    data["projects"][0]["datasets"] = ["shared", "Shared"]
    message = problems_of(tmp_path, data)
    assert "has 3 problems" in message
    assert "trigger repository gitea.fn.svc:4000/gitea_admin/trigger-repo is listed twice" in message
    assert "repositories.results[0]: no provider for the host of unknown.example/gitea_admin/results-repo in this file" in message
    assert "dataset shared is listed twice" in message


def test_what_the_file_does_not_hold_is_not_a_problem_here_because_it_may_be_on_the_node(tmp_path):
    data = node_data()
    data["repositories"]["triggers"][0]["secret"] = "other-creds"
    data["datasets"][0]["secret"] = "other-creds"
    data["projects"][0]["datasets"] = ["elsewhere"]
    data["projects"][0]["repositories"]["triggers"][0]["repository"] = "http://gitea.fn.svc:4000/gitea_admin/other"
    data["projects"][0]["repositories"]["results"]["repository"] = "http://gitea.fn.svc:4000/gitea_admin/other2"

    node = load(tmp_path, data)

    assert node.projects[0].datasets == ["elsewhere"]


def test_a_project_has_exactly_one_results_repository(tmp_path):
    data = node_data()
    results = data["projects"][0]["repositories"]["results"]
    data["projects"][0]["repositories"]["results"] = [results, results]
    assert "exactly one results repository" in problems_of(tmp_path, data)
    del data["projects"][0]["repositories"]["results"]
    assert "results: Field required" in problems_of(tmp_path, data)


def test_base_branch_must_be_set_and_watch_dir_not_empty(tmp_path):
    data = node_data()
    trigger = data["projects"][0]["repositories"]["triggers"][0]
    del trigger["base_branch"]
    trigger["watch_dir"] = "./"
    message = problems_of(tmp_path, data)
    assert "base_branch: Field required" in message
    assert "watch_dir must name a directory, not the whole repository" in message


def test_a_gitea_repository_must_be_under_the_admin_user_of_the_context(tmp_path):
    data = node_data()
    data["repositories"]["triggers"][0]["uri"] = "http://gitea.fn.svc:4000/someone/trigger-repo"
    data["projects"][0]["repositories"]["triggers"][0]["repository"] = "http://gitea.fn.svc:4000/someone/trigger-repo"
    node = load(tmp_path, data)

    assert check_gitea_owners(node, "gitea_admin") == [
        "repositories.triggers[0]: gitea.fn.svc:4000/someone/trigger-repo is owned by someone, "
        "not the Gitea admin user gitea_admin"
    ]
    assert [problem.split(":")[0] for problem in check_gitea_owners(node, "Someone")] == ["repositories.results[0]"]


def test_a_node_file_holds_no_node_block(tmp_path):
    data = node_data()
    data["node"] = {"url": "http://localhost:5000", "kube_context": "kind-fn", "keycloak_namespace": "keycloak"}

    assert "node: Extra inputs are not permitted" in problems_of(tmp_path, data)


def test_a_file_may_hold_any_subset_of_the_sections(tmp_path):
    data = node_data()
    only_projects = {"version": 1, "projects": data["projects"]}
    only_globals = {key: value for key, value in data.items() if key != "projects"}

    assert load(tmp_path, only_projects).projects[0].name == "alpha"
    assert load(tmp_path, only_globals).projects == []


def test_a_github_repository_may_be_under_any_owner(tmp_path):
    data = node_data()
    data["providers"].append({"type": "github", "uri": "https://github.com"})
    data["repositories"]["triggers"].append({"uri": "https://github.com/Org/repo", "secret": "trigger-creds"})
    load(tmp_path, data)


def test_oauth_app_names_must_be_unique_and_need_the_gitea_section(tmp_path):
    data = node_data()
    data["secrets"]["results-creds"]["gitea_oauth"]["app"] = "sensor"
    del data["gitea"]
    message = problems_of(tmp_path, data)
    assert "Gitea OAuth app name sensor is used twice" in message
    assert "a gitea_oauth secret needs the gitea section" in message


def test_gitea_provider_must_name_a_gitea_provider(tmp_path):
    data = node_data()
    data["gitea"]["provider"] = "gitea-elsewhere"
    assert "gitea.provider gitea-elsewhere is not the name of a gitea provider" in problems_of(tmp_path, data)


def test_duplicates_are_refused(tmp_path):
    data = node_data()
    data["datasets"].append(dict(data["datasets"][0], name="SHARED"))
    data["projects"].append(copy.deepcopy(data["projects"][0]))
    data["repositories"]["triggers"].append(dict(data["repositories"]["triggers"][0]))
    message = problems_of(tmp_path, data)
    assert "dataset name shared is listed twice" in message
    assert "project name alpha is listed twice" in message
    assert "trigger repository gitea.fn.svc:4000/gitea_admin/trigger-repo is listed twice" in message


def test_a_key_given_twice_in_the_yaml_is_refused(tmp_path):
    text = yaml.safe_dump(node_data()) + "version: 1\n"
    with pytest.raises(click.ClickException, match="duplicate keys: version"):
        load(tmp_path, text)


def test_a_trigger_directory_may_not_overlap_a_results_directory_of_the_same_repository(tmp_path):
    data = node_data()
    data["repositories"]["results"][0]["uri"] = TRIGGER
    project = data["projects"][0]["repositories"]
    project["results"]["repository"] = TRIGGER
    project["results"]["target_dir"] = "specs/out"
    message = problems_of(tmp_path, data)
    assert "watch_dir specs/ and project alpha's results target_dir specs/out overlap" in message
    project["results"]["target_dir"] = "results"
    load(tmp_path, data)


def test_the_overlap_check_spans_the_projects_of_the_file(tmp_path):
    data = node_data()
    data["repositories"]["results"].append({"uri": TRIGGER, "secret": "results-creds"})
    other = copy.deepcopy(data["projects"][0])
    other["name"] = "beta"
    other["repositories"]["triggers"] = []
    other["repositories"]["results"] = {"repository": TRIGGER, "target_dir": "specs/", "base_branch": "main"}
    data["projects"].append(other)
    assert "project alpha: watch_dir specs/ and project beta's results target_dir specs/ overlap" in problems_of(tmp_path, data)


def test_directories_compare_by_segments():
    assert normalise_dir("./specs//a/") == "specs/a"
    assert dirs_overlap("specs/", "specs/a") and dirs_overlap("specs/a", "specs") and dirs_overlap("specs", "specs/")
    assert not dirs_overlap("specs", "specs2") and not dirs_overlap("a/b", "a/c")
    assert dirs_overlap("", "specs")
    with pytest.raises(ValueError):
        normalise_dir("a/../b")


def test_file_references_resolve_from_the_node_file_and_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    data = node_data()
    data["secrets"]["dataset-creds"]["values"] = {
        "RELATIVE": {"file": "keys/a.pem"}, "HOME": {"file": "~/b.pem"}, "ABSOLUTE": {"file": "/etc/c.pem"},
    }
    node = load(tmp_path, data)
    values = node.secrets["dataset-creds"].values
    assert values["RELATIVE"].file == tmp_path.resolve() / "keys/a.pem"
    assert values["HOME"].file == tmp_path / "home/b.pem"
    assert values["ABSOLUTE"].file == Path("/etc/c.pem")


def test_limit_to_project_keeps_the_project_and_what_it_references(tmp_path):
    data = node_data()
    data["providers"].append({"type": "github", "uri": "https://github.com"})
    data["secrets"]["gh-creds"] = {"values": {"APP_ID": {"env": "X"}}}
    data["repositories"]["triggers"].append({"uri": "https://github.com/org/repo", "secret": "gh-creds"})
    data["repositories"]["results"].append({"uri": "https://github.com/org/repo", "secret": "gh-creds"})
    data["datasets"].append(dict(data["datasets"][0], name="other-dataset"))
    other = copy.deepcopy(data["projects"][0])
    other.update(name="beta", datasets=["other-dataset"])
    other["repositories"] = {
        "triggers": [{"repository": "https://github.com/org/repo", "watch_dir": "in/", "base_branch": "main"}],
        "results": {"repository": "https://github.com/org/repo", "target_dir": "out/", "base_branch": "main"},
    }
    data["projects"].append(other)
    node = load(tmp_path, data)

    limited = limit_to_project(node, "beta")
    assert [p.name for p in limited.projects] == ["beta"]
    assert [p.resolved_name for p in limited.providers] == ["github-github.com"]
    assert set(limited.secrets) == {"gh-creds", "dataset-creds"}
    assert [d.name for d in limited.datasets] == ["other-dataset"]
    assert [r.uri for r in limited.repositories.triggers] == ["github.com/org/repo"]
    with pytest.raises(click.ClickException, match="Project nope is not in the node file, which has: alpha, beta"):
        limit_to_project(node, "nope")


def test_limit_to_project_keeps_what_the_file_has_when_the_project_also_names_things_on_the_node(tmp_path):
    data = node_data()
    data["projects"][0]["datasets"] = ["shared", "on-the-node"]
    node = load(tmp_path, data)

    limited = limit_to_project(node, "alpha")

    assert limited.projects[0].datasets == ["shared", "on-the-node"]
    assert [d.name for d in limited.datasets] == ["Shared"]


def test_check_sources_says_set_or_missing_and_never_holds_a_value(tmp_path, monkeypatch):
    monkeypatch.setenv("SET_ME", "s3cret-value")
    monkeypatch.delenv("NOT_SET", raising=False)
    present = tmp_path / "key.pem"
    present.write_text("s3cret-file")
    found = {("ns", "there", "key"): "s3cret-k8s"}

    def fake_k8s(name, namespace, key):
        if (namespace, name) == ("ns", "gone"):
            raise ApiException(status=404)
        if (namespace, name) == ("ns", "forbidden"):
            raise ApiException(status=403)
        return found[(namespace, name, key)]

    monkeypatch.setattr(loader, "get_k8s_secret", fake_k8s)
    data = node_data()
    data["secrets"]["dataset-creds"]["values"] = {
        "A": {"env": "SET_ME"}, "B": {"env": "NOT_SET"},
        "C": {"file": str(present)}, "D": {"file": str(tmp_path / "absent.pem")},
        "E": {"k8s_secret": {"name": "there", "namespace": "ns", "key": "key"}},
        "F": {"k8s_secret": {"name": "gone", "namespace": "ns", "key": "key"}},
        "G": {"k8s_secret": {"name": "there", "namespace": "ns", "key": "nokey"}},
        "H": {"generate": {"length": 12}},
    }
    sources = check_sources(load(tmp_path, data).secrets["dataset-creds"])
    assert [(s.key, s.state) for s in sources] == [
        ("A", SET), ("B", MISSING), ("C", SET), ("D", MISSING), ("E", SET), ("F", MISSING), ("G", MISSING),
        ("H", GENERATED),
    ]
    assert sources[0].where == "env SET_ME"
    assert "s3cret" not in repr(sources)

    data["secrets"]["dataset-creds"]["values"] = {"X": {"k8s_secret": {"name": "forbidden", "namespace": "ns", "key": "k"}}}
    with pytest.raises(ApiException):
        check_sources(load(tmp_path, data).secrets["dataset-creds"])


def test_a_gitea_oauth_secret_has_no_values_to_check(tmp_path):
    assert check_sources(load(tmp_path, node_data()).secrets["trigger-creds"]) == []


EXAMPLES = ROOT / "bootstrap" / "examples"
NOT_IN_IMAGE = pytest.mark.skipif(
    not (EXAMPLES / "globals-gitea.yaml").exists(), reason="the repo's bootstrap/examples files are not in the test image"
)


@NOT_IN_IMAGE
@pytest.mark.parametrize("name", sorted(path.relative_to(EXAMPLES).as_posix() for path in EXAMPLES.rglob("*.yaml") if path.name != "context.yaml"))
def test_every_committed_example_loads_and_holds_no_secret_value(name):
    node = load_node_file(EXAMPLES / name)
    assert (len(node.projects) > 0) == name.startswith("projects/")
    assert "hunter" not in (EXAMPLES / name).read_text()


@NOT_IN_IMAGE
def test_every_committed_project_resolves_against_the_committed_global_files_and_datasets():
    """The split is right: what a project names is in some globals file, or in an experiment's dataset.yaml"""
    globals_ = [load_node_file(path) for path in EXAMPLES.glob("globals-*.yaml")]
    datasets = [load_node_file(path) for path in (ROOT / "experiments").glob("*/dataset.yaml")]
    held = {
        "dataset": {d.name for node in globals_ + datasets for d in node.datasets},
        "trigger": {r.uri for node in globals_ for r in node.repositories.triggers},
        "results": {r.uri for node in globals_ for r in node.repositories.results},
    }
    for path in (EXAMPLES / "projects").glob("*.yaml"):
        for project in load_node_file(path).projects:
            assert set(project.datasets) <= held["dataset"], path
            assert {t.repository for t in project.repositories.triggers} <= held["trigger"], path
            assert project.repositories.results.repository in held["results"], path


def context_text(extra: str = "") -> str:
    return (
        "node:\n  url: http://localhost:5000\n  kube_context: kind-fn\n  keycloak_namespace: keycloak\n"
        "  env_file: .ctx.env\n" + extra
    )


@pytest.fixture
def no_default_env(monkeypatch):
    monkeypatch.delenv("FNCLI_DEFAULT_PROJECT", raising=False)
    monkeypatch.delenv("FNCLI_DEFAULT_TRIGGER_TYPE", raising=False)


def test_a_context_has_the_node_and_optional_defaults_and_finds_its_env_file_upwards(tmp_path, no_default_env):
    (tmp_path / ".ctx.env").write_text("")
    folder = tmp_path / "bootstrap"
    folder.mkdir()
    path = folder / "context.yaml"
    path.write_text(context_text("defaults:\n  project: demo-gitea\n  trigger_type: pr\n"))

    context = load_context(path)

    assert context.path == path
    assert (context.node.url, context.node.kube_context, context.node.gitea_admin_user) == (
        "http://localhost:5000", "kind-fn", "gitea_admin"
    )
    assert context.node.env_file == tmp_path / ".ctx.env"
    assert (context.defaults.project, context.defaults.trigger_type) == ("demo-gitea", "pr")


def test_a_context_without_defaults_has_none(tmp_path, no_default_env):
    path = tmp_path / "context.yaml"
    path.write_text(context_text())

    assert load_context(path).defaults.project is None and load_context(path).defaults.trigger_type is None


def test_the_env_wins_over_the_defaults_of_the_context_file(tmp_path, monkeypatch, no_default_env):
    path = tmp_path / "context.yaml"
    path.write_text(context_text("defaults:\n  project: from-file\n  trigger_type: pr\n"))
    monkeypatch.setenv("FNCLI_DEFAULT_PROJECT", "from-env")
    monkeypatch.setenv("FNCLI_DEFAULT_TRIGGER_TYPE", "api")

    defaults = load_context(path).defaults

    assert (defaults.project, defaults.trigger_type) == ("from-env", "api")


def test_a_default_trigger_type_that_is_not_one_is_refused(tmp_path, monkeypatch, no_default_env):
    path = tmp_path / "context.yaml"
    path.write_text(context_text())
    monkeypatch.setenv("FNCLI_DEFAULT_TRIGGER_TYPE", "carrier-pigeon")

    with pytest.raises(click.ClickException, match="must be one of pr, api, not carrier-pigeon"):
        load_context(path)


def test_a_context_refuses_unknown_keys_and_needs_the_node(tmp_path):
    path = tmp_path / "context.yaml"
    path.write_text("defaults:\n  project: x\n  colour: red\n")

    with pytest.raises(click.ClickException) as error:
        load_context(path)

    assert "node: Field required" in error.value.message and "defaults.colour: Extra inputs are not permitted" in error.value.message


@NOT_IN_IMAGE
def test_the_example_context_loads(no_default_env):
    context = load_context(EXAMPLES / "context.yaml")

    assert context.node.kube_context == "kind-fn" and context.defaults.project == "demo-gitea"
