import pytest

from app.helpers.exceptions import InvalidRequest
from app.dtos.task_spec import TaskSpec

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
        assert TaskSpec.from_api_body(body).model_dump() == {**EXPECTED_DEFAULTS, **expected}

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
            TaskSpec.from_api_body(body)


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
        assert TaskSpec.from_pr_spec(spec).model_dump() == {**EXPECTED_DEFAULTS, **expected}

    @pytest.mark.parametrize("spec", [
        {},
        {"env": {"K": "v"}},
        {"image": ""},
        {"image": "img:1", "env": None},
        {"image": "img:1", "unknown": True},
    ])
    def test_invalid(self, spec):
        with pytest.raises(InvalidRequest):
            TaskSpec.from_pr_spec(spec)

    def test_does_not_mutate_the_input(self):
        spec = {"docker_image": "img:1"}
        TaskSpec.from_pr_spec(spec)
        assert spec == {"docker_image": "img:1"}


class TestSameSpecFromBothShapes:
    def test_equivalent(self):
        api = TaskSpec.from_api_body({
            "name": "t", "executors": [{"image": "img:1", "env": {"K": "v"}}], "tags": {"dataset_name": "ds"}
        })
        pr = TaskSpec.from_pr_spec({
            "name": "t", "docker_image": "img:1", "env": {"K": "v"}, "dataset": "ds", "tags": {"dataset_name": "ds"}
        })
        assert api == pr
