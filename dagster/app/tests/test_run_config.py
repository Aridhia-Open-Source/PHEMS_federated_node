import dagster as dg

from app.definitions.jobs import k8s_pipes_job
from app.definitions.run_config import build_run_config
from app.models import Dataset, TaskSpec

DATASET = Dataset(
    id=1,
    secret={
        "id": 3, "project_id": 1, "label": "cdm-creds", "provider": "K8S",
        "key": "cdm-creds-abc", "namespace": "fn", "enabled": True,
    },
    name="cdm",
    host="db.host",
    port=5432,
    read_schema="cdm",
    write_schema="results",
    type="postgres",
    enabled=True,
    slug="cdm",
    url="https://db.host/cdm",
)
DATASET_FIELDS = {
    "dataset": {
        "name": "cdm",
        "host": "db.host",
        "port": 5432,
        "type": "postgres",
        "read_schema": "cdm",
        "write_schema": "results",
        "secret": {"provider": "K8S", "key": "cdm-creds-abc", "namespace": "fn"},
    }
}


def expected(**op_config):
    return {"ops": {"k8s_pipes_op": {"config": {**DATASET_FIELDS, **op_config}}}}


def test_build_run_config():
    spec = TaskSpec(image="a/b:1", dataset_id=1, env={"K": "v"})

    assert build_run_config(spec, DATASET) == expected(env={"K": "v"}, docker_image="a/b:1")


def test_the_specs_config_is_in_the_run_config():
    config = {"threshold": 0.5, "labels": ["a", None, True], "nested": {"deep": {"k": []}}}
    spec = TaskSpec(image="a/b:1", dataset_id=1, env={}, config=config)

    assert build_run_config(spec, DATASET)["ops"]["k8s_pipes_op"]["config"]["config"] == config


def test_a_spec_with_a_config_is_a_valid_run_config_of_the_job():
    """The job's op config schema takes any JSON object as the task's config."""
    config = {"threshold": 0.5, "labels": ["a", None, True], "nested": {"deep": {"k": []}}, "empty": None}
    spec = TaskSpec(image="a/b:1", dataset_id=1, env={"K": "v"}, config=config)

    result = dg.validate_run_config(k8s_pipes_job, build_run_config(spec, DATASET))

    assert result["ops"]["k8s_pipes_op"]["config"]["config"] == config


def test_a_spec_with_an_empty_config_still_has_a_config():
    spec = TaskSpec(image="a/b:1", env={}, config={})

    assert build_run_config(spec, None)["ops"]["k8s_pipes_op"]["config"]["config"] == {}


def test_a_task_without_a_dataset_has_no_dataset_in_its_run_config():
    spec = TaskSpec(image="a/b:1", env={})

    config = build_run_config(spec, None)

    assert config == {"ops": {"k8s_pipes_op": {"config": {"env": {}, "docker_image": "a/b:1"}}}}
    assert dg.validate_run_config(k8s_pipes_job, config)


def test_the_spec_has_no_resources():
    assert "resources" not in TaskSpec.model_fields
    assert "resources" not in build_run_config(TaskSpec(image="a/b:1", env={}), None)["ops"]["k8s_pipes_op"]["config"]
