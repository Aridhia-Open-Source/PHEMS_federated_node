import pytest
from pydantic import ValidationError

from app.models import PullRequestSpec


def test_image_is_kept():
    assert PullRequestSpec(image="a/b:1").image == "a/b:1"


def test_docker_image_is_normalised_to_image():
    spec = PullRequestSpec.model_validate({"docker_image": "a/b:1"})

    assert spec.image == "a/b:1"
    assert "docker_image" not in spec.model_dump()


def test_image_wins_over_docker_image():
    assert PullRequestSpec.model_validate({"image": "a/b:1", "docker_image": "c/d:1"}).image == "a/b:1"


def test_defaults():
    assert PullRequestSpec(image="a/b:1").model_dump() == {
        "name": None, "image": "a/b:1", "env": {}, "params": {}, "dataset": None,
        "tags": {}, "resources": {}, "repository": None,
    }


@pytest.mark.parametrize("data", [{}, {"env": {}}, {"image": ""}, {"docker_image": ""}, ["image"]])
def test_a_missing_or_empty_image_is_rejected(data):
    with pytest.raises(ValidationError):
        PullRequestSpec.model_validate(data)


@pytest.mark.parametrize("field", ["command", "description", "bogus"])
def test_extra_fields_are_rejected(field):
    with pytest.raises(ValidationError):
        PullRequestSpec.model_validate({"image": "a/b:1", field: "x"})
