import json

import pytest

from app.dtos import task_spec
from app.dtos.task_spec import PrSpecFile, TaskSpecRequest
from app.helpers.const import TASK_ENV_MAX_BYTES, TASK_IMAGE_MAX_LENGTH, TASK_NAME_MAX_LENGTH
from app.helpers.exceptions import InvalidRequest

NO_COMPUTE = {"requests": None, "limits": None}
EXPECTED_DEFAULTS = {
    "name": None, "env": {}, "params": {}, "dataset": None, "tags": {}, "config": None,
    "compute": NO_COMPUTE, "metadata": None, "repository": None,
}


@pytest.fixture(autouse=True)
def compute_config(monkeypatch):
    """The chart's defaults, whatever the environment the tests run in has."""
    for name, value in (
        ("TASK_COMPUTE_MAX_CPU", "4"), ("TASK_COMPUTE_MAX_MEMORY", "16Gi"),
        ("TASK_COMPUTE_DEFAULT_LIMIT_CPU", "2"), ("TASK_COMPUTE_DEFAULT_LIMIT_MEMORY", "4Gi"),
    ):
        monkeypatch.setattr(task_spec, name, value)


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
            {
                "image": "img:1", "env": {"K": "v"}, "dataset": "ds", "tags": {"team": "a", "run": "1"},
                "config": {"a": [1, {"b": None}]}, "compute": {"requests": {"cpu": "500m"}, "limits": {"memory": "2Gi"}},
            },
            {
                "image": "img:1", "env": {"K": "v"}, "dataset": "ds", "tags": {"team": "a", "run": "1"},
                "config": {"a": [1, {"b": None}]},
                "compute": {"requests": {"cpu": "500m", "memory": None}, "limits": {"cpu": None, "memory": "2Gi"}},
            },
        ),
        # An empty config is a config, an absent one is none
        ({"image": "img:1", "config": {}}, {"image": "img:1", "config": {}}),
        ({"image": "img:1", "config": None}, {"image": "img:1"}),
        ({"image": "img:1", "compute": {}}, {"image": "img:1"}),
    ])
    def test_normalised(self, spec, expected):
        assert TaskSpecRequest.from_pr_spec(pr_file(spec)).model_dump() == {**EXPECTED_DEFAULTS, **expected}

    @pytest.mark.parametrize("metadata", [
        None, "text", 5, [1, 2], {"client": {"ticket": "ABC-1"}, "any": ["thing", None]},
        # Not validated, so not even the spec's own rules apply to it
        {"image": 1, "env": "x", "a/b": 2},
    ])
    def test_metadata_is_any_json_and_kept_as_it_is(self, metadata):
        parsed = TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1"}, metadata=metadata))
        assert parsed.model_dump() == {**EXPECTED_DEFAULTS, "image": "img:1", "metadata": metadata}

    def test_no_metadata_is_none(self):
        assert TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1"})).metadata is None

    def test_metadata_does_not_belong_in_the_spec(self):
        with pytest.raises(InvalidRequest, match=r"spec.metadata: Extra inputs are not permitted"):
            TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1", "metadata": {}}))

    @pytest.mark.parametrize("spec", [
        {},
        {"env": {"K": "v"}},
        {"image": ""},
        {"image": "img:1", "env": None},
        {"image": "img:1", "unknown": True},
        # What the file does not take
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
        # compute is an object of requests and limits
        {"image": "img:1", "compute": None},
        {"image": "img:1", "compute": []},
        {"image": "img:1", "compute": {"limit": {"cpu": "1"}}},
        {"image": "img:1", "compute": {"limits": {"gpu": "1"}}},
        {"image": "img:1", "compute": {"limits": "1"}},
        {"image": "img:1", "compute": {"limits": {"cpu": 1}}},
    ])
    def test_invalid(self, spec):
        with pytest.raises(InvalidRequest):
            TaskSpecRequest.from_pr_spec(pr_file(spec))

    def test_unknown_spec_keys_are_named(self):
        with pytest.raises(InvalidRequest) as error:
            TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1", "params": {}, "name": "n"}))
        assert "spec.params: Extra inputs are not permitted" in error.value.description
        assert "spec.name: Extra inputs are not permitted" in error.value.description

    @pytest.mark.parametrize("key", [
        "a/b", "dagster/max_retries", "dagster-k8s/config", "user/team", "", "a b", "a:b", "ÿ", "a" * 64
    ])
    def test_invalid_tag_key_is_named(self, key):
        with pytest.raises(InvalidRequest) as error:
            TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1", "tags": {key: "x"}}))
        assert f"spec.tags.{key}" in error.value.description and "should match pattern" in error.value.description

    @pytest.mark.parametrize("key", ["k", "_k", "_trigger", "Team", "a.b", "a-b", "a_b.c-D9", "dagster", "1", "a" * 63])
    def test_plain_tag_keys_are_free(self, key):
        assert TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1", "tags": {key: "x"}})).tags == {key: "x"}

    @pytest.mark.parametrize("spec_raw", [
        "not json", "", "{}", "[]", "null", '{"spec": ["image"]}', '{"spec": null}', '{"metadata": {}}',
        '{"spec": {"image": "img:1"}, "note": "x"}',
        '{"spec": {"image": "img:1"}, "name": "n"}',
        '{"image": "img:1"}',
    ])
    def test_invalid_file(self, spec_raw):
        with pytest.raises(InvalidRequest, match="Invalid spec file"):
            TaskSpecRequest.from_pr_spec(spec_raw)

    def test_unknown_top_level_keys_are_named(self):
        with pytest.raises(InvalidRequest, match="note: Extra inputs are not permitted"):
            TaskSpecRequest.from_pr_spec('{"spec": {"image": "img:1"}, "note": "x"}')

    def test_no_spec_is_named(self):
        with pytest.raises(InvalidRequest, match="spec: Field required"):
            TaskSpecRequest.from_pr_spec('{"metadata": {}}')

    def test_the_cause_is_readable(self):
        with pytest.raises(InvalidRequest) as error:
            TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1", "env": {"CDM_SCHEMA": "x"}}))
        assert error.value.description == "Invalid spec file: spec.env: env key CDM_SCHEMA is reserved"


class TestCompute:
    """What a spec may ask for: the chart's max and default limit, set by compute_config as 4 / 16Gi and 2 / 4Gi."""
    def parse(self, compute):
        return TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1", "compute": compute}))

    @pytest.mark.parametrize("compute", [
        {"limits": {"cpu": "1", "memory": "1Gi"}},
        {"limits": {"cpu": "500m"}},
        {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"cpu": "1", "memory": "1Gi"}},
        # A request alone has to fit the default limit it gets
        {"requests": {"cpu": "2", "memory": "4Gi"}},
        {"requests": {"cpu": "2000m"}},
        # At the max
        {"limits": {"cpu": "4", "memory": "16Gi"}},
        {"limits": {"cpu": "4000m", "memory": "16384Mi"}},
        # A limit equal to its request
        {"requests": {"cpu": "1"}, "limits": {"cpu": "1"}},
        # Over the default limit is fine with a limit of its own
        {"requests": {"cpu": "3", "memory": "8Gi"}, "limits": {"cpu": "4", "memory": "16Gi"}},
        # Memory units
        {"limits": {"memory": "2e9"}},
        {"limits": {"memory": "512M"}},
        {"limits": {"memory": "1048576k"}},
        {"limits": {"cpu": "0.5"}},
    ])
    def test_accepted(self, compute):
        parsed = self.parse(compute)
        assert parsed.compute.model_dump(exclude_none=True) == compute

    @pytest.mark.parametrize("compute", [
        {"limits": {"cpu": "abc"}}, {"limits": {"cpu": "0.1m"}}, {"limits": {"cpu": ".5"}}, {"limits": {"cpu": "m"}},
        {"limits": {"cpu": ""}}, {"limits": {"cpu": "1Gi"}}, {"limits": {"cpu": "5.24.1"}},
        {"limits": {"memory": "Gi"}}, {"limits": {"memory": "1K"}}, {"limits": {"memory": "1.5Gi"}},
        {"limits": {"memory": "100ki"}}, {"limits": {"memory": "100mi"}}, {"limits": {"memory": "1GiGi"}},
        {"limits": {"memory": ""}}, {"requests": {"memory": "Mi100"}},
    ])
    def test_a_quantity_has_to_be_valid(self, compute):
        with pytest.raises(InvalidRequest, match="should match pattern"):
            self.parse(compute)

    @pytest.mark.parametrize("compute, message", [
        ({"limits": {"memory": "32Gi"}}, "compute.limits.memory 32Gi is over the node max 16Gi"),
        ({"limits": {"cpu": "5"}}, "compute.limits.cpu 5 is over the node max 4"),
        ({"limits": {"cpu": "4001m"}}, "compute.limits.cpu 4001m is over the node max 4"),
        ({"requests": {"cpu": "8"}, "limits": {"cpu": "16"}}, "compute.requests.cpu 8 is over the node max 4"),
        ({"requests": {"memory": "17Gi"}}, "compute.requests.memory 17Gi is over the node max 16Gi"),
        ({"limits": {"memory": "17179869185"}}, "compute.limits.memory 17179869185 is over the node max 16Gi"),
    ])
    def test_nothing_over_the_max(self, compute, message):
        with pytest.raises(InvalidRequest, match=message):
            self.parse(compute)

    @pytest.mark.parametrize("compute, message", [
        ({"requests": {"cpu": "1"}, "limits": {"cpu": "500m"}}, "compute.limits.cpu 500m is lower than its request 1"),
        (
            {"requests": {"memory": "2Gi"}, "limits": {"memory": "1Gi"}},
            "compute.limits.memory 1Gi is lower than its request 2Gi"
        ),
        ({"requests": {"cpu": "0.5"}, "limits": {"cpu": "400m"}}, "compute.limits.cpu 400m is lower than its request 0.5"),
    ])
    def test_a_limit_is_not_lower_than_its_request(self, compute, message):
        with pytest.raises(InvalidRequest, match=message):
            self.parse(compute)

    @pytest.mark.parametrize("compute, message", [
        (
            {"requests": {"cpu": "3"}},
            "compute.requests.cpu 3 is over the default limit 2, give a compute.limits.cpu with it"
        ),
        ({"requests": {"memory": "8Gi"}}, "compute.requests.memory 8Gi is over the default limit 4Gi"),
        # The limit has to be for the same resource
        ({"requests": {"cpu": "3"}, "limits": {"memory": "1Gi"}}, "compute.requests.cpu 3 is over the default limit 2"),
        (
            {"requests": {"memory": "8Gi"}, "limits": {"cpu": "1"}},
            "compute.requests.memory 8Gi is over the default limit 4Gi"
        ),
    ])
    def test_a_request_without_a_limit_fits_the_default_limit(self, compute, message):
        with pytest.raises(InvalidRequest, match=message):
            self.parse(compute)

    def test_only_what_the_spec_gave_is_kept(self):
        assert self.parse({"limits": {"memory": "1Gi"}}).compute.model_dump(exclude_none=True) == {
            "limits": {"memory": "1Gi"}
        }
        assert self.parse({}).compute.model_dump(exclude_none=True) == {}
        assert TaskSpecRequest.from_pr_spec(pr_file({"image": "img:1"})).compute.model_dump(exclude_none=True) == {}

    def test_the_config_comes_from_the_environment(self, monkeypatch):
        monkeypatch.setattr(task_spec, "TASK_COMPUTE_MAX_CPU", "8")
        monkeypatch.setattr(task_spec, "TASK_COMPUTE_DEFAULT_LIMIT_CPU", "6")
        assert self.parse({"requests": {"cpu": "6"}, "limits": {"cpu": "8"}}).compute.limits.cpu == "8"
        assert self.parse({"requests": {"cpu": "6"}}).compute.requests.cpu == "6"
        with pytest.raises(InvalidRequest, match="compute.requests.cpu 7 is over the default limit 6"):
            self.parse({"requests": {"cpu": "7"}})
        with pytest.raises(InvalidRequest, match="compute.limits.cpu 9 is over the node max 8"):
            self.parse({"limits": {"cpu": "9"}})


class TestSpecFileSchema:
    """The schema of the spec file is generated from PrSpecFile, so its fields and rules are stated on the model."""
    schema = PrSpecFile.model_json_schema()

    def test_the_top_level_has_a_spec_and_a_metadata(self):
        assert set(self.schema["properties"]) == {"spec", "metadata"}
        assert self.schema["required"] == ["spec"]
        assert self.schema["additionalProperties"] is False

    def test_the_spec_has_its_fields(self):
        spec = self.schema["$defs"]["PrSpec"]
        assert set(spec["properties"]) == {"image", "dataset", "env", "tags", "config", "compute"}
        assert spec["required"] == ["image"]
        assert spec["additionalProperties"] is False

    def test_compute_has_requests_and_limits_of_cpu_and_memory(self):
        defs = self.schema["$defs"]
        assert set(defs["Compute"]["properties"]) == {"requests", "limits"}
        assert set(defs["ComputeQuantities"]["properties"]) == {"cpu", "memory"}
        assert defs["Compute"]["additionalProperties"] is False
        assert defs["ComputeQuantities"]["additionalProperties"] is False

    def test_keys_and_quantities_are_patterns(self):
        spec = self.schema["$defs"]["PrSpec"]["properties"]
        for field in ("env", "tags"):
            assert len(spec[field]["patternProperties"]) == 1 and spec[field]["additionalProperties"] is False
        quantities = self.schema["$defs"]["ComputeQuantities"]["properties"]
        assert any("pattern" in option for option in quantities["cpu"]["anyOf"])
        assert any("pattern" in option for option in quantities["memory"]["anyOf"])

    def test_the_rules_only_a_validator_has_are_in_the_descriptions(self):
        defs = self.schema["$defs"]
        env = defs["PrSpec"]["properties"]["env"]["description"]
        for reserved in (
            "ARTIFACT_PATH", "CDM_SCHEMA", "WRITE_SCHEMA", "DB_USERNAME", "DB_PASSWORD", "CONNECTION_STRING",
            "CONFIG_PATH", "DAGSTER_", "KUBERNETES_", str(TASK_ENV_MAX_BYTES)
        ):
            assert reserved in env
        assert "node max" in defs["Compute"]["properties"]["limits"]["description"]
        assert "lower than its request" in defs["Compute"]["properties"]["limits"]["description"]
        assert "default limit" in defs["Compute"]["properties"]["requests"]["description"]
        assert "65536" in self.schema["properties"]["metadata"]["description"]


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
        with pytest.raises(InvalidRequest, match="should match pattern"):
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

    @pytest.mark.parametrize("key", [
        "DAGSTER", "MY_DAGSTER_VAR", "KUBERNETES", "DB_USER", "CONFIG", "ARTIFACT_PATHS", "_DAGSTER_X"
    ])
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
