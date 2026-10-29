import json

import pytest

from app.helpers.const import TASK_ENV_MAX_BYTES, TASK_IMAGE_MAX_LENGTH, TASK_NAME_MAX_LENGTH
from app.helpers.exceptions import InvalidRequest
from app.dtos.task_spec import TaskSpecRequest

EXPECTED_DEFAULTS = {
    "name": None, "env": {}, "params": {},
    "dataset": None, "tags": {}, "config": None, "metadata": None, "repository": None,
}


class TestFromApiBody:
    @pytest.mark.parametrize("body, expected", [
        (
            {"name": "t", "executors": [{"image": "img:1"}]},
            {"name": "t", "image": "img:1"},
        ),
        (
            # The API's tags only name the dataset and its resources are validated elsewhere, neither is kept
            {
                "name": "t", "repository": "org/repo",
                "executors": [{"image": "img:1", "env": {"K": 1}}],
                "tags": {"dataset_name": "ds", "other": "x"},
                "resources": {"limits": {"cpu": "1"}, "requests": {"cpu": "100m"}},
            },
            {
                "name": "t", "repository": "org/repo", "image": "img:1",
                "env": {"K": 1}, "dataset": "ds",
            },
        ),
        (
            # The dataset id alone does not name a dataset
            {"name": "t", "executors": [{"image": "img:1"}], "tags": {"dataset_id": 3}},
            {"name": "t", "image": "img:1"},
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


def pr_file(spec, **top) -> str:
    return json.dumps({"spec": spec, **top})


class TestFromPrSpec:
    @pytest.mark.parametrize("spec, expected", [
        ({"image": "img:1"}, {"image": "img:1"}),
        (
            {"image": "img:1", "env": {"K": "v"}, "dataset": "ds", "tags": {"team": "a", "run": "1"}, "config": {"a": [1, {"b": None}]}},
            {"image": "img:1", "env": {"K": "v"}, "dataset": "ds", "tags": {"team": "a", "run": "1"}, "config": {"a": [1, {"b": None}]}},
        ),
        # An empty config is a config, an absent one is none
        ({"image": "img:1", "config": {}}, {"image": "img:1", "config": {}}),
        ({"image": "img:1", "config": None}, {"image": "img:1"}),
    ])
    def test_normalised(self, spec, expected):
        assert TaskSpecRequest.from_pr_spec(pr_file(spec)).model_dump() == {**EXPECTED_DEFAULTS, **expected}

    @pytest.mark.parametrize("metadata", [
        None, "text", 5, [1, 2], {"client": {"ticket": "ABC-1"}, "any": ["thing", None]},
        # Not validated, so not even the spec's own rules apply to it
        {"image": 1, "env": "x", "dagster/tag": 2},
    ])
    def test_metadata_is_any_json_and_kept_as_it_is(self, metadata):
        parsed = TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1"}, metadata=metadata))
        assert parsed.model_dump() == {**EXPECTED_DEFAULTS, "image": "img:1", "metadata": metadata}

    def test_no_metadata_is_none(self):
        assert TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1"})).metadata is None

    def test_metadata_does_not_belong_in_the_spec(self):
        with pytest.raises(InvalidRequest, match=r"unknown key\(s\) \['metadata'\] in spec"):
            TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1", "metadata": {}}))

    @pytest.mark.parametrize("spec", [
        {},
        {"env": {"K": "v"}},
        {"image": ""},
        {"image": "img:1", "env": None},
        {"image": "img:1", "unknown": True},
        # What the file no longer takes
        {"image": "img:1", "name": "n"},
        {"image": "img:1", "params": {"p": 1}},
        {"image": "img:1", "repository": "org/repo"},
        {"image": "img:1", "resources": {"limits": {"cpu": "1"}}},
        {"docker_image": "img:1"},
        {"image": "img:1", "docker_image": "img:1"},
        # tags are text to text, with plain keys
        {"image": "img:1", "tags": {"k": 1}},
        {"image": "img:1", "tags": {"k": None}},
        {"image": "img:1", "tags": ["k"]},
        {"image": "img:1", "tags": {"a/b": "x"}},
        {"image": "img:1", "tags": {"dagster/max_retries": "3"}},
        {"image": "img:1", "tags": {"fine": "x", "bad key": "1"}},
        # config is an object
        {"image": "img:1", "config": []},
        {"image": "img:1", "config": "text"},
        {"image": "img:1", "config": 5},
    ])
    def test_invalid(self, spec):
        with pytest.raises(InvalidRequest):
            TaskSpecRequest.from_pr_spec(pr_file(spec))

    def test_unknown_spec_keys_are_named(self):
        with pytest.raises(InvalidRequest, match=r"unknown key\(s\) \['name', 'params'\] in spec"):
            TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1", "params": {}, "name": "n"}))

    @pytest.mark.parametrize("key", ["a/b", "dagster/max_retries", "dagster-k8s/config", "user/team", "", "a b", "a:b", "ÿ", "k\n", "a" * 64])
    def test_invalid_tag_key_is_named(self, key):
        with pytest.raises(InvalidRequest, match=f"tag key {key} is not valid"):
            TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1", "tags": {key: "x"}}))

    @pytest.mark.parametrize("key", ["k", "_k", "_trigger", "Team", "a.b", "a-b", "a_b.c-D9", "dagster", "1", "a" * 63])
    def test_plain_tag_keys_are_free(self, key):
        assert TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1", "tags": {key: "x"}})).tags == {key: "x"}

    @pytest.mark.parametrize("spec_raw", [
        "not json", "{}", "[]", '{"spec": ["image"]}', '{"spec": null}', '{"metadata": {}}',
        '{"spec": {"image": "img:1"}, "note": "x"}',
        '{"spec": {"image": "img:1"}, "name": "n"}',
        '{"image": "img:1"}',
    ])
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

    @pytest.mark.parametrize("key", [
        "ARTIFACT_PATH", "CDM_SCHEMA", "WRITE_SCHEMA", "DB_USERNAME", "DB_PASSWORD", "CONNECTION_STRING", "CONFIG_PATH",
        "DAGSTER_HOME", "DAGSTER_", "KUBERNETES_SERVICE_HOST",
    ])
    def test_reserved_env_keys(self, key):
        with pytest.raises(InvalidRequest, match=f"env key {key} is reserved"):
            self.build(env={key: "v"})

    @pytest.mark.parametrize("key", [
        "cdm_schema", "Write_Schema", "artifact_path", "Db_Password", "config_path", "dagster_home", "Kubernetes_x",
    ])
    def test_reserved_env_keys_are_compared_upper_cased(self, key):
        with pytest.raises(InvalidRequest, match=f"env key {key} is reserved"):
            self.build(env={key: "v"})

    @pytest.mark.parametrize("key", ["DAGSTER", "MY_DAGSTER_VAR", "KUBERNETES", "DB_USER", "CONFIG", "ARTIFACT_PATHS", "_DAGSTER_X"])
    def test_other_env_keys_are_free(self, key):
        assert self.build(env={key: "v"}).env == {key: "v"}

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
            "executors": [{"image": "img:1", "env": {"K": "v"}}], "tags": {"dataset_name": "ds"}
        })
        pr = TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1", "env": {"K": "v"}, "dataset": "ds"}))
        assert api == pr
