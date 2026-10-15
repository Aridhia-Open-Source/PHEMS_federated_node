import pytest

from app.helpers.git_uri import normalise_repo_uri, validate_api_uri


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


@pytest.mark.parametrize("uri, expected", [
    ("https://github.com:443/org/repo", "github.com/org/repo"),
    ("http://host:80/o/r", "host/o/r"),
    ("https://host:8443/o/r", "host:8443/o/r"),
    ("http://host:443/o/r", "host:443/o/r"),
    ("host:443/o/r", "host:443/o/r"),
])
def test_only_the_default_port_of_the_scheme_is_dropped(uri, expected):
    assert normalise_repo_uri(uri) == expected


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


@pytest.mark.parametrize("api_uri, uri", [
    ("https://api.github.com", "github.com/org/repo"),
    ("https://API.GitHub.com/", "github.com/org/repo"),
    ("http://gitea.fn.svc:4000/api/v1", "gitea.fn.svc:4000/org/repo"),
    ("https://git.example.com/api/v1", "git.example.com/org/repo"),
    ("https://api.github.com:443", "github.com/org/repo"),
])
def test_an_api_uri_on_the_repository_host_is_accepted(api_uri, uri):
    assert validate_api_uri(api_uri, uri) == api_uri


@pytest.mark.parametrize("api_uri, uri", [
    ("ftp://git.example.com/api", "git.example.com/org/repo"),
    ("git.example.com/api", "git.example.com/org/repo"),
    ("https://user:pass@git.example.com/api", "git.example.com/org/repo"),
    ("https://evil.example.com/api", "git.example.com/org/repo"),
    ("http://gitea.fn.svc:3000/api/v1", "gitea.fn.svc:4000/org/repo"),
    ("https://git.example.com.evil.com/api", "git.example.com/org/repo"),
    ("https://github.com", "github.com/org/repo"),
    ("https://git.example.com/api", "github.com/org/repo"),
])
def test_an_api_uri_that_is_not_on_the_repository_host_is_rejected(api_uri, uri):
    with pytest.raises(ValueError):
        validate_api_uri(api_uri, uri)
