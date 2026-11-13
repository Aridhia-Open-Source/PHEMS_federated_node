import pytest
import yaml

from fncli.cmds.common import ResultsRepoConfig, TriggerRepoConfig
from fncli.nodefile.schema import NodeSpec

# Only the deploy settings are read from the env now: the node, the project and its repositories come from the context
# file and the node
ENV = {"NAMESPACE": "fn"}

NODE = NodeSpec(url="http://localhost:5000", kube_context="kind-fn", keycloak_namespace="keycloak")

GITEA = {"gitea_url": "http://gitea.fn.svc:3000", "gitea_api_uri": "http://gitea.fn.svc:3000/api/v1"}
TRIGGER = {
    "node": NODE, "project_name": "proj", "repo": "trigger", "repo_uri": "http://gitea.fn.svc:3000/gitea_admin/trigger",
    "watch_dir": "specs/", "base_branch": "main", **GITEA,
}
RESULTS = {
    "node": NODE, "project_name": "proj", "repo": "results", "repo_uri": "http://gitea.fn.svc:3000/gitea_admin/results",
    "target_dir": "out/", "base_branch": "main", **GITEA,
}


def trigger_config(**changes) -> TriggerRepoConfig:
    """A project's trigger repository config, as load_repo_config builds it from the node"""
    return TriggerRepoConfig(**{**TRIGGER, **changes})


def results_config(**changes) -> ResultsRepoConfig:
    return ResultsRepoConfig(**{**RESULTS, **changes})


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Every deploy setting the configs require, as the dev .env provides them."""
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def context_file(tmp_path, monkeypatch):
    """A context file for the commands' --context (FNCLI_CONTEXT), with no defaults"""
    path = tmp_path / "context.yaml"
    path.write_text(yaml.safe_dump({"node": {"url": "http://nexus:5000", "kube_context": "kind-fn", "keycloak_namespace": "keycloak"}}))
    monkeypatch.setenv("FNCLI_CONTEXT", str(path))
    monkeypatch.delenv("FNCLI_DEFAULT_PROJECT", raising=False)
    return path
