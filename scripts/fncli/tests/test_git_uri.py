import pytest

from fncli.dagster.git_uri import normalise_repo_uri


@pytest.mark.parametrize("uri", [
    "github.com/org/repo",
    "github.com/org/repo/",
    "github.com/org/repo.git",
    "github.com/org/repo.git/",
    "http://github.com/org/repo",
    "https://GitHub.com/Org/Repo.git",
    "  https://github.com/org/repo/  ",
])
def test_the_forms_of_one_repository_normalise_alike(uri):
    assert normalise_repo_uri(uri) == "github.com/org/repo"


def test_the_port_and_a_sub_path_are_kept():
    assert normalise_repo_uri("http://gitea.fn.svc:3000/gitea/owner/repo.git") == (
        "gitea.fn.svc:3000/gitea/owner/repo"
    )


def test_a_uri_that_is_already_normalised_is_unchanged():
    assert normalise_repo_uri("gitea.fn.svc:3000/org/repo") == "gitea.fn.svc:3000/org/repo"


@pytest.mark.parametrize("uri", [
    "",
    "github.com",
    "github.com/org",
    "org/repo",
    "https://",
    "ssh://github.com/org/repo",
    "https://user:pass@github.com/org/repo",
])
def test_what_is_not_a_repository_address_is_rejected(uri):
    with pytest.raises(ValueError):
        normalise_repo_uri(uri)
