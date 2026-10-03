import pytest

from app.definitions.run_config import build_run_config
from app.models import Dataset

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


def expected(**op_config):
    return {"ops": {"k8s_pipes_op": {"config": {**DATASET_FIELDS, **op_config}}}}


@pytest.mark.parametrize(
    "spec, config",
    [
        ({"image": "ghcr.io/o/i:1"}, expected(env={}, docker_image="ghcr.io/o/i:1")),
        ({"docker_image": "ghcr.io/o/i:1"}, expected(env={}, docker_image="ghcr.io/o/i:1")),
        ({"image": "a/b:1", "docker_image": "c/d:1"}, expected(env={}, docker_image="a/b:1")),
        ({"image": "a/b:1", "env": None}, expected(env={}, docker_image="a/b:1")),
        (
            {"image": "a/b:1", "env": {"K": "v"}, "name": "ignored", "dataset": "other"},
            expected(env={"K": "v"}, docker_image="a/b:1"),
        ),
    ],
)
def test_build_run_config(spec, config):
    assert build_run_config(spec, DATASET) == config


@pytest.mark.parametrize("spec", [{}, {"env": {"K": "v"}}, {"image": ""}])
def test_a_spec_without_an_image_raises(spec):
    with pytest.raises(ValueError, match="missing 'image'"):
        build_run_config(spec, DATASET)
