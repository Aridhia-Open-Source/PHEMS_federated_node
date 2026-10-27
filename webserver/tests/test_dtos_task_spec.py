import json

import pytest

from app.helpers.const import TASK_ENV_MAX_BYTES, TASK_IMAGE_MAX_LENGTH, TASK_NAME_MAX_LENGTH
from app.helpers.exceptions import InvalidRequest
from app.dtos.task_spec import TaskSpecRequest

EXPECTED_DEFAULTS = {
    "name": None, "env": {}, "params": {},
    "dataset": None, "tags": {}, "resources": {}, "repository": None,
}


class TestFromApiBody:
    @pytest.mark.parametrize("body, expected", [
        (
            {"name": "t", "executors": [{"image": "img:1"}]},
            {"name": "t", "image": "img:1"},
        ),
        (
            {
                "name": "t", "repository": "org/repo",
                "executors": [{"image": "img:1", "env": {"K": 1}}],
                "tags": {"dataset_name": "ds", "other": "x"},
                "resources": {"limits": {"cpu": "1"}, "requests": {"cpu": "100m"}},
            },
            {
                "name": "t", "repository": "org/repo", "image": "img:1",
                "env": {"K": 1}, "dataset": "ds",
                "tags": {"dataset_name": "ds", "other": "x"},
                "resources": {"limits": {"cpu": "1"}, "requests": {"cpu": "100m"}},
            },
        ),
        (
            # The dataset id alone does not name a dataset, it survives in the tags
            {"name": "t", "executors": [{"image": "img:1"}], "tags": {"dataset_id": 3}},
            {"name": "t", "image": "img:1", "tags": {"dataset_id": 3}},
        ),
    ])
    def test_normalised(self, body, expected):
        assert TaskSpecRequest.from_api_body(body).model_dump() == {**EXPECTED_DEFAULTS, **expected}

    @pytest.mark.parametrize("body", [
        {},
        {"executors": []},
        {"executors": {"image": "img:1"}},
        {"executors": ["img:1"]},
        {"executors": [{}]},
        {"executors": [{"image": 1}]},
    ])
    def test_invalid(self, body):
        with pytest.raises(InvalidRequest):
            TaskSpecRequest.from_api_body(body)


def pr_file(spec) -> str:
    return json.dumps({"spec": spec})


class TestFromPrSpec:
    @pytest.mark.parametrize("spec, expected", [
        ({"image": "img:1"}, {"image": "img:1"}),
        ({"docker_image": "img:1"}, {"image": "img:1"}),
        ({"image": "img:1", "docker_image": "other:1"}, {"image": "img:1"}),
        (
            {"image": "img:1", "name": "n", "env": {"K": "v"}, "params": {"p": 1}, "dataset": "ds"},
            {"image": "img:1", "name": "n", "env": {"K": "v"}, "params": {"p": 1}, "dataset": "ds"},
        ),
    ])
    def test_normalised(self, spec, expected):
        assert TaskSpecRequest.from_pr_spec(pr_file(spec)).model_dump() == {**EXPECTED_DEFAULTS, **expected}

    @pytest.mark.parametrize("spec", [
        {},
        {"env": {"K": "v"}},
        {"image": ""},
        {"image": "img:1", "env": None},
        {"image": "img:1", "unknown": True},
    ])
    def test_invalid(self, spec):
        with pytest.raises(InvalidRequest):
            TaskSpecRequest.from_pr_spec(pr_file(spec))

    @pytest.mark.parametrize("spec_raw", ["not json", "{}", "[]", '{"spec": ["image"]}', '{"spec": null}'])
    def test_invalid_file(self, spec_raw):
        with pytest.raises(InvalidRequest, match="Invalid spec file"):
            TaskSpecRequest.from_pr_spec(spec_raw)


class TestValidation:
    """The rules every spec goes through, whichever shape it came in."""
    def build(self, **fields):
        return TaskSpecRequest.build(**{"image": "img:1", **fields})

    @pytest.mark.parametrize("length, valid", [
        (TASK_IMAGE_MAX_LENGTH - 1, True), (TASK_IMAGE_MAX_LENGTH, True), (TASK_IMAGE_MAX_LENGTH + 1, False),
    ])
    def test_image_length(self, length, valid):
        if valid:
            assert len(self.build(image="a" * length).image) == length
        else:
            with pytest.raises(InvalidRequest, match="image"):
                self.build(image="a" * length)

    @pytest.mark.parametrize("length, valid", [
        (TASK_NAME_MAX_LENGTH - 1, True), (TASK_NAME_MAX_LENGTH, True), (TASK_NAME_MAX_LENGTH + 1, False),
    ])
    def test_name_length(self, length, valid):
        if valid:
            assert len(self.build(name="a" * length).name) == length
        else:
            with pytest.raises(InvalidRequest, match="name"):
                self.build(name="a" * length)

    @pytest.mark.parametrize("key", ["K", "_k", "KEY_1", "a1_B2"])
    def test_env_key_accepted(self, key):
        assert self.build(env={key: "v"}).env == {key: "v"}

    @pytest.mark.parametrize("key", ["1K", "K-1", "K 1", "K.1", "", "K=1", "ÿ", "K\n"])
    def test_env_key_format(self, key):
        with pytest.raises(InvalidRequest, match="must match"):
            self.build(env={key: "v"})

    @pytest.mark.parametrize("key", ["CDM_SCHEMA", "WRITE_SCHEMA", "DB_USERNAME", "DB_PASSWORD"])
    def test_reserved_env_keys(self, key):
        with pytest.raises(InvalidRequest, match="reserved"):
            self.build(env={key: "v"})

    def test_reserved_env_keys_are_case_sensitive(self):
        assert self.build(env={"cdm_schema": "v"}).env == {"cdm_schema": "v"}

    @staticmethod
    def env_of_size(size):
        """An env whose JSON is exactly `size` bytes."""
        overhead = len(json.dumps({"K": ""}).encode())
        return {"K": "v" * (size - overhead)}

    def test_env_size_boundary(self):
        env = self.env_of_size(TASK_ENV_MAX_BYTES)
        assert len(json.dumps(env).encode()) == TASK_ENV_MAX_BYTES
        assert self.build(env=env).env == env
        with pytest.raises(InvalidRequest, match="bytes limit"):
            self.build(env=self.env_of_size(TASK_ENV_MAX_BYTES + 1))

    def test_dataset_is_optional(self):
        assert self.build().dataset is None

    def test_api_body_is_validated_too(self):
        with pytest.raises(InvalidRequest, match="reserved"):
            TaskSpecRequest.from_api_body({"executors": [{"image": "img:1", "env": {"CDM_SCHEMA": "x"}}]})


class TestSameSpecFromBothShapes:
    def test_equivalent(self):
        api = TaskSpecRequest.from_api_body({
            "name": "t", "executors": [{"image": "img:1", "env": {"K": "v"}}], "tags": {"dataset_name": "ds"}
        })
        pr = TaskSpecRequest.from_pr_spec(pr_file({
            "name": "t", "docker_image": "img:1", "env": {"K": "v"}, "dataset": "ds", "tags": {"dataset_name": "ds"}
        }))
        assert api == pr
