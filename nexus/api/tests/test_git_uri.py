import pytest

from app.helpers.git_uri import (
    normalise_provider_uri, normalise_repo_path, normalise_repo_uri, validate_api_uri
)


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


@pytest.mark.parametrize("uri, normalised", [
    ("https://GitHub.com/", "https://github.com"),
    ("https://github.com:443", "https://github.com"),
    ("http://gitea.fn.svc:4000/", "http://gitea.fn.svc:4000"),
    ("  https://git.example.com/Gitea/ ", "https://git.example.com/gitea"),
])
def test_a_provider_uri_is_normalised(uri, normalised):
    assert normalise_provider_uri(uri) == normalised


@pytest.mark.parametrize("uri", [
    "",
    "github.com",
    "ssh://github.com",
    "https://",
    "https://user:pass@github.com",
])
def test_what_is_not_a_provider_address_is_rejected(uri):
    with pytest.raises(ValueError):
        normalise_provider_uri(uri)


@pytest.mark.parametrize("repo_path, normalised", [
    ("org/repo", "org/repo"),
    ("  /Org/Repo.git/ ", "org/repo"),
])
def test_a_repo_path_is_normalised(repo_path, normalised):
    assert normalise_repo_path(repo_path) == normalised


@pytest.mark.parametrize("repo_path", ["", "org", "org/", "/repo", "a/b/c", "https://github.com/org/repo"])
def test_what_is_not_a_repo_path_is_rejected(repo_path):
    with pytest.raises(ValueError):
        normalise_repo_path(repo_path)


@pytest.mark.parametrize("api_uri, uri", [
    ("https://api.github.com", "https://github.com"),
    ("https://API.GitHub.com/", "https://github.com"),
    ("http://gitea.fn.svc:4000/api/v1", "http://gitea.fn.svc:4000"),
    ("https://git.example.com/api/v1", "https://git.example.com"),
    ("https://api.github.com:443", "https://github.com"),
])
def test_an_api_uri_on_the_provider_host_is_accepted(api_uri, uri):
    assert validate_api_uri(api_uri, uri) == api_uri


@pytest.mark.parametrize("api_uri, uri", [
    ("ftp://git.example.com/api", "https://git.example.com"),
    ("git.example.com/api", "https://git.example.com"),
    ("https://user:pass@git.example.com/api", "https://git.example.com"),
    ("https://evil.example.com/api", "https://git.example.com"),
    ("http://gitea.fn.svc:3000/api/v1", "http://gitea.fn.svc:4000"),
    ("https://git.example.com.evil.com/api", "https://git.example.com"),
    ("https://github.com", "https://github.com"),
    ("https://git.example.com/api", "https://github.com"),
])
def test_an_api_uri_that_is_not_on_the_provider_host_is_rejected(api_uri, uri):
    with pytest.raises(ValueError):
        validate_api_uri(api_uri, uri)
