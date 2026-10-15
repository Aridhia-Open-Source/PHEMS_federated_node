from app.definitions.run_config import build_run_config
from app.models import Dataset, TaskSpec

DATASET = Dataset(
    id=1,
    project_id=1,
    secret={
        "id": 3, "project_id": 1, "label": "cdm-creds", "provider": "K8S",
        "key": "cdm-creds-abc", "namespace": "fn",
    },
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


def test_a_task_without_a_dataset_has_no_dataset_in_its_run_config():
    spec = TaskSpec(image="a/b:1", env={})

    config = build_run_config(spec, None)

    assert config == {"ops": {"k8s_pipes_op": {"config": {"env": {}, "docker_image": "a/b:1"}}}}
