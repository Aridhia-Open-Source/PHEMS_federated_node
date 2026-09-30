import pytest
from unittest.mock import MagicMock

from app.definitions.run_config import build_run_config
from app.definitions.sensors.gitea.pr_trigger import PullRequestTriggerSensor as GiteaTrigger
from app.definitions.sensors.github.pr_trigger import PullRequestTriggerSensor as GithubTrigger
from app.models import Dataset, PullRequest, Registry

DATASET = Dataset(
    id=1,
    project_id=1,
    k8s_secret_name="cdm-creds",
    name="cdm",
    host="db.host",
    port=5432,
    read_schema="cdm",
    write_schema="results",
    type="postgres",
    slug="cdm",
    url="https://db.host/cdm",
)
DATASET_FIELDS = {
    "dataset_name": "cdm",
    "dataset_host": "db.host",
    "dataset_port": 5432,
    "dataset_type": "postgres",
    "dataset_read_schema": "cdm",
    "dataset_write_schema": "results",
    "dataset_k8s_secret_name": "cdm-creds",
}
GHCR = Registry(id=1, url="ghcr.io")


def expected(**op_config):
    return {"ops": {"k8s_pipes_op": {"config": {**DATASET_FIELDS, **op_config}}}}


@pytest.mark.parametrize(
    "spec, registries, config",
    [
        ({"image": "ghcr.io/o/i:1"}, [], expected(env={}, docker_image="ghcr.io/o/i:1")),
        ({"docker_image": "ghcr.io/o/i:1"}, [], expected(env={}, docker_image="ghcr.io/o/i:1")),
        (
            {"image": "a/b:1", "docker_image": "c/d:1"},
            [],
            expected(env={}, docker_image="a/b:1"),
        ),
        ({"image": "a/b:1", "env": None}, [], expected(env={}, docker_image="a/b:1")),
        (
            {"image": "a/b:1", "env": {"K": "v"}, "name": "ignored", "dataset": "other"},
            [],
            expected(env={"K": "v"}, docker_image="a/b:1"),
        ),
        (
            {"image": "ghcr.io/o/i:1"},
            [GHCR],
            expected(env={}, docker_image="ghcr.io/o/i:1", image_pull_secret="ghcr-io"),
        ),
        (
            {"image": "docker.io/library/alpine:3"},
            [GHCR],
            expected(env={}, docker_image="docker.io/library/alpine:3"),
        ),
    ],
)
def test_build_run_config(spec, registries, config):
    assert build_run_config(spec, DATASET, registries) == config


@pytest.mark.parametrize("spec", [{}, {"env": {"K": "v"}}, {"image": ""}])
def test_a_spec_without_an_image_raises(spec):
    with pytest.raises(ValueError, match="missing 'image'"):
        build_run_config(spec, DATASET, [])


@pytest.mark.parametrize("sensor_class, trigger", [(GiteaTrigger, "gitea"), (GithubTrigger, "github")])
@pytest.mark.parametrize("registries", [[], [GHCR]])
def test_the_legacy_sensors_build_the_config_the_function_does(sensor_class, trigger, registries):
    backend_api = MagicMock()
    backend_api.get_dataset.return_value = DATASET
    backend_api.get_registries.return_value = registries
    sensor = sensor_class(context=MagicMock(), backend_api=backend_api, **{f"{trigger}_api": MagicMock()})
    repo = MagicMock(id=1, uri="host/org/repo", dataset_id=1)
    spec = {"docker_image": "ghcr.io/o/i:1", "env": {"K": "v"}}
    pr = MagicMock(spec=PullRequest, number=5, title="t", trigger_repository_id=1, payload=spec)

    request = sensor._make_run_request(repo, pr)

    assert request.run_config == build_run_config(spec, DATASET, registries)
    assert request.run_key == "1/5"


def test_a_failed_registry_lookup_leaves_the_pull_secret_out():
    backend_api = MagicMock()
    backend_api.get_dataset.return_value = DATASET
    backend_api.get_registries.side_effect = RuntimeError("500")
    sensor = GiteaTrigger(context=MagicMock(), backend_api=backend_api, gitea_api=MagicMock())
    pr = MagicMock(spec=PullRequest, number=5, title="t", trigger_repository_id=1, payload={"image": "ghcr.io/o/i:1"})

    request = sensor._make_run_request(MagicMock(id=1, uri="host/org/repo", dataset_id=1), pr)

    assert request.run_config == expected(env={}, docker_image="ghcr.io/o/i:1")
