"""
Short-lived git tokens (ADR 0023): the three token sources with the provider's HTTP mocked, the cache in the
repository's secret and its five-minute window, the secret patch that writes only the changed keys, and
POST /global/repositories/{triggers,results}/<id>/token with each of its refusals. The Kubernetes secret is
k8s_client's read mock; a refusal runs with no HTTP mocked, so any call to a provider fails the test.
"""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from typing import NamedTuple
from urllib.parse import parse_qs

import jwt
import pytest
import responses
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.helpers.base_model import db
from app.helpers.exceptions import GitProviderError, InvalidRequest
from app.helpers.git_tokens import mint_token
from app.helpers.kubernetes import KubernetesClient
from app.models.git_provider import GitProvider
from app.models.project_results_repository import ProjectResultsRepository
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.trigger_repository import TriggerRepository

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = PRIVATE_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
GITHUB_KEYS = {"APP_ID": "123456", "INSTALLATION_ID": "42", "PRIVATE_KEY": PRIVATE_PEM}
GITEA_KEYS = {"CLIENT_ID": "client-id", "CLIENT_SECRET": "client-secret", "REFRESH_TOKEN": "old-refresh"}
GITHUB_TOKEN_URL = "https://api.github.com/app/installations/42/access_tokens"
WIRE_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


def now() -> datetime:
    return datetime.now(tz=timezone.utc)


def use_secret(k8s_client, **values):
    """What the secret holds, as the Kubernetes read returns it."""
    k8s_client["read_namespaced_secret_mock"].return_value.data = {
        key: KubernetesClient.encode_secret_value(value) for key, value in values.items()
    }


def cache_of(repo, permission: str, token: str, expires_at: datetime) -> dict[str, str]:
    key = f"CACHED_TOKEN_{repo.id}_{permission}"
    return {key: token, f"{key}_EXPIRES_AT": expires_at.isoformat()}


def encoded(values: dict[str, str]) -> dict[str, str]:
    return {key: KubernetesClient.encode_secret_value(value) for key, value in values.items()}


def github_answer(token="ghs_installation", expires_in=timedelta(hours=1)) -> dict:
    return {"token": token, "expires_at": (now() + expires_in).strftime("%Y-%m-%dT%H:%M:%SZ")}


def patch_body(k8s_client, secret) -> dict:
    """The body of the one patch of the secret."""
    patch = k8s_client["patch_namespaced_secret_mock"]
    patch.assert_called_once()
    assert patch.call_args.args == (secret.key, secret.namespace)
    return patch.call_args.kwargs["body"]


@pytest.fixture
def gitea_repo(client, global_secret) -> TriggerRepository:
    """A trigger repository on the in-cluster Gitea: http, on port 4000, as the dev cluster has it."""
    provider = GitProvider(name="gitea", type="gitea", uri="http://gitea:4000", api_uri="http://gitea:4000/api/v1")
    provider.add()
    repo = TriggerRepository(provider.id, "org/repo", global_secret.id)
    repo.add()
    return repo


# ---------------------------------------------------------------- the sources

def test_github_app_mints_a_read_token_for_the_one_repository(k8s_client, global_secret, global_trigger_repo):
    use_secret(k8s_client, **GITHUB_KEYS)
    answer = github_answer()
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, GITHUB_TOKEN_URL, json=answer, status=201)
        token, expires_at = mint_token(global_secret, global_trigger_repo, "read")
        request = rsps.calls[0].request

    assert token == "ghs_installation"
    assert expires_at == datetime.fromisoformat(answer["expires_at"])
    assert json.loads(request.body) == {
        "repositories": ["triggers"], "permissions": {"contents": "read", "pull_requests": "read"}
    }
    claims = jwt.decode(request.headers["Authorization"].removeprefix("Bearer "), PRIVATE_KEY.public_key(), algorithms=["RS256"])
    assert claims["iss"] == "123456"
    assert claims["exp"] - claims["iat"] == 600  # issued a minute back, valid nine minutes on
    assert 8 * 60 < claims["exp"] - time.time() <= 9 * 60


def test_github_app_mints_a_write_token_for_a_results_repository(k8s_client, global_secret, global_results_repo):
    use_secret(k8s_client, **GITHUB_KEYS)
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, GITHUB_TOKEN_URL, json=github_answer(), status=201)
        mint_token(global_secret, global_results_repo, "write")
        request = rsps.calls[0].request

    assert json.loads(request.body) == {
        "repositories": ["results-global"], "permissions": {"contents": "write", "pull_requests": "write"}
    }


def test_gitea_exchanges_the_refresh_token_and_writes_the_new_one_back(k8s_client, global_secret, gitea_repo):
    use_secret(k8s_client, **GITEA_KEYS)
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, "http://gitea:4000/login/oauth/access_token", json={
            "access_token": "gta_access", "token_type": "bearer", "expires_in": 3600, "refresh_token": "new-refresh"
        })
        before = now()
        token, expires_at = mint_token(global_secret, gitea_repo, "read")
        form = parse_qs(rsps.calls[0].request.body)

    assert token == "gta_access"
    assert before + timedelta(seconds=3600) <= expires_at <= now() + timedelta(seconds=3600)
    assert form == {
        "grant_type": ["refresh_token"], "client_id": ["client-id"],
        "client_secret": ["client-secret"], "refresh_token": ["old-refresh"],
    }
    # The new refresh token and the cache, and not CLIENT_ID or CLIENT_SECRET
    assert patch_body(k8s_client, global_secret) == {"data": encoded({
        "REFRESH_TOKEN": "new-refresh", **cache_of(gitea_repo, "read", "gta_access", expires_at),
    })}


def test_a_static_token_is_returned_as_it_is_and_never_cached(k8s_client, global_secret, global_trigger_repo):
    use_secret(k8s_client, TOKEN="static-token", **cache_of(global_trigger_repo, "read", "stale", now() + timedelta(hours=1)))
    with responses.RequestsMock():  # no request is made
        token, expires_at = mint_token(global_secret, global_trigger_repo, "read")

    assert token == "static-token"
    assert timedelta(minutes=59) < expires_at - now() <= timedelta(hours=1)
    k8s_client["patch_namespaced_secret_mock"].assert_not_called()


def test_app_keys_win_over_a_static_token_left_in_the_secret(k8s_client, global_secret, global_trigger_repo):
    use_secret(k8s_client, TOKEN="static-token", **GITHUB_KEYS)
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, GITHUB_TOKEN_URL, json=github_answer(), status=201)
        assert mint_token(global_secret, global_trigger_repo, "read")[0] == "ghs_installation"


def test_a_secret_with_no_complete_credential_is_a_409(k8s_client, global_secret, global_trigger_repo):
    use_secret(k8s_client, APP_ID="1", CLIENT_ID="c", REFRESH_TOKEN="r")  # parts of two credentials
    with pytest.raises(InvalidRequest) as refused:
        mint_token(global_secret, global_trigger_repo, "read")
    assert refused.value.code == 409


def test_a_provider_that_refuses_is_a_502_and_nothing_is_cached(client, k8s_client, global_secret, global_trigger_repo):
    use_secret(k8s_client, **GITHUB_KEYS)
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, GITHUB_TOKEN_URL, json={"message": "Bad credentials"}, status=401)
        with pytest.raises(GitProviderError) as refused:
            mint_token(global_secret, global_trigger_repo, "read")
    assert refused.value.code == 502 and "Bad credentials" in refused.value.description
    k8s_client["patch_namespaced_secret_mock"].assert_not_called()


# ---------------------------------------------------------------- the cache

def test_a_cached_token_is_reused_while_more_than_five_minutes_are_left(k8s_client, global_secret, global_trigger_repo):
    expires_at = now() + timedelta(minutes=6)
    use_secret(k8s_client, **GITHUB_KEYS, **cache_of(global_trigger_repo, "read", "cached", expires_at))
    with responses.RequestsMock():  # nothing is minted
        assert mint_token(global_secret, global_trigger_repo, "read") == ("cached", expires_at)
    k8s_client["patch_namespaced_secret_mock"].assert_not_called()


@pytest.mark.parametrize("left", [timedelta(minutes=4), timedelta(seconds=-1)], ids=["under five minutes", "expired"])
def test_a_cached_token_with_five_minutes_or_less_left_is_minted_again(k8s_client, global_secret, global_trigger_repo, left):
    use_secret(k8s_client, **GITHUB_KEYS, **cache_of(global_trigger_repo, "read", "cached", now() + left))
    answer = github_answer("ghs_fresh")
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, GITHUB_TOKEN_URL, json=answer, status=201)
        token, expires_at = mint_token(global_secret, global_trigger_repo, "read")

    assert token == "ghs_fresh"
    assert patch_body(k8s_client, global_secret) == {"data": encoded(cache_of(global_trigger_repo, "read", "ghs_fresh", expires_at))}


def test_the_cache_is_per_repository_and_permission(k8s_client, global_secret, global_trigger_repo):
    """A token cached for another repository, or for write, is not this repository's read token."""
    later = now() + timedelta(hours=1)
    use_secret(
        k8s_client, **GITHUB_KEYS,
        CACHED_TOKEN_999_read="other-repo", CACHED_TOKEN_999_read_EXPIRES_AT=later.isoformat(),
        **cache_of(global_trigger_repo, "write", "write-token", later),
    )
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, GITHUB_TOKEN_URL, json=github_answer("ghs_read"), status=201)
        assert mint_token(global_secret, global_trigger_repo, "read")[0] == "ghs_read"


def test_the_patch_writes_only_the_changed_keys(k8s_client, global_secret, global_trigger_repo):
    """Everything else in the secret, PRIVATE_KEY included, is left to the patch's merge."""
    use_secret(k8s_client, **GITHUB_KEYS, EXTRA="kept")
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, GITHUB_TOKEN_URL, json=github_answer(), status=201)
        mint_token(global_secret, global_trigger_repo, "read")

    assert set(patch_body(k8s_client, global_secret)["data"]) == {
        f"CACHED_TOKEN_{global_trigger_repo.id}_read", f"CACHED_TOKEN_{global_trigger_repo.id}_read_EXPIRES_AT"
    }


# ---------------------------------------------------------------- the routes

class Kit(NamedTuple):
    url: str
    permission: str
    repo: object
    assignment: object
    project: object


@pytest.fixture(params=["triggers", "results"])
def kit(request, project, k8s_client) -> Kit:
    """A repository of each kind assigned to the project, its secret holding a GitHub App."""
    if request.param == "triggers":
        request.getfixturevalue("assigned_trigger_repo")
        repo = request.getfixturevalue("global_trigger_repo")
        assignment = ProjectTriggerRepository.query.filter_by(project_id=project.id).one()
        permission = "read"
    else:
        request.getfixturevalue("assigned_results_repo")
        repo = request.getfixturevalue("global_results_repo")
        assignment = ProjectResultsRepository.query.filter_by(project_id=project.id).one()
        permission = "write"
    use_secret(k8s_client, **GITHUB_KEYS)
    return Kit(f"/global/repositories/{request.param}/{repo.id}/token", permission, repo, assignment, project)


@pytest.mark.parametrize("body", [{}, {"project_id": None}, "project"], ids=["no project", "null project", "project"])
def test_the_route_returns_a_token_and_its_expiry(client, system_headers, kit, body):
    body = {"project_id": kit.project.id} if body == "project" else body
    answer = github_answer()
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, GITHUB_TOKEN_URL, json=answer, status=201)
        response = client.post(kit.url, json=body, headers=system_headers)
        asked = json.loads(rsps.calls[0].request.body)

    assert response.status_code == 200, response.json
    assert set(response.json) == {"token", "expires_at"} and response.json["token"] == "ghs_installation"
    assert WIRE_DATETIME.match(response.json["expires_at"])
    assert response.json["expires_at"] == datetime.fromisoformat(answer["expires_at"]).strftime("%Y-%m-%d %H:%M:%S")
    assert asked["permissions"] == {"contents": kit.permission, "pull_requests": kit.permission}
    assert asked["repositories"] == [kit.repo.repo_path.split("/")[1]]


def test_the_route_reuses_the_cache(client, system_headers, k8s_client, kit):
    use_secret(k8s_client, **GITHUB_KEYS, **cache_of(kit.repo, kit.permission, "cached", now() + timedelta(minutes=30)))
    with responses.RequestsMock():
        response = client.post(kit.url, json={"project_id": kit.project.id}, headers=system_headers)
    assert response.status_code == 200 and response.json["token"] == "cached"


def test_an_unknown_repository_is_a_404(client, system_headers):
    for kind in ("triggers", "results"):
        assert client.post(f"/global/repositories/{kind}/999/token", json={}, headers=system_headers).status_code == 404


@pytest.mark.parametrize("body", [{"project_id": "1"}, {"project_id": True}, {"project_id": 1.5}, {"repository": 1}],
                         ids=["string", "bool", "float", "unknown field"])
def test_a_malformed_body_is_a_400(client, system_headers, kit, body):
    assert client.post(kit.url, json=body, headers=system_headers).status_code == 400


def test_a_secret_with_no_credential_is_a_409(client, system_headers, k8s_client, kit):
    use_secret(k8s_client, USERNAME="u")
    assert client.post(kit.url, json={}, headers=system_headers).status_code == 409


def test_a_provider_failure_is_a_502(client, system_headers, kit):
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, GITHUB_TOKEN_URL, json={"message": "Not Found"}, status=404)
        response = client.post(kit.url, json={}, headers=system_headers)
    assert response.status_code == 502 and "Not Found" in response.json["error"]


def test_only_the_system_user_may_ask(client, admin_headers, post_json_user_header, k8s_client, kit):
    for headers in (admin_headers, post_json_user_header):
        assert client.post(kit.url, json={}, headers=headers).status_code == 403
    k8s_client["read_namespaced_secret_mock"].assert_not_called()


# What refuses a token (ADR 0008): the repository, its provider and its secret, with or without a project; then a
# revoked or deleted project or resource. Switched off is not refused for the project and its resource, see below
REFUSALS = {
    "repository disabled": (lambda k: setattr(k.repo, "enabled", False), False),
    "repository revoked": (lambda k: setattr(k.repo, "revoked", True), False),
    "provider disabled": (lambda k: setattr(k.repo.provider, "enabled", False), False),
    "provider revoked": (lambda k: setattr(k.repo.provider, "revoked", True), False),
    "secret disabled": (lambda k: setattr(k.repo.secret, "enabled", False), False),
    "secret deleted": (lambda k: k.repo.secret.soft_delete(), False),
    "project revoked": (lambda k: setattr(k.project, "revoked", True), True),
    "project deleted": (lambda k: k.project.soft_delete(), True),
    "resource revoked": (lambda k: setattr(k.assignment, "revoked", True), True),
    "resource deleted": (lambda k: k.assignment.soft_delete(), True),
}


@pytest.mark.parametrize("switch", REFUSALS)
def test_a_disabled_or_revoked_repository_secret_project_or_resource_is_refused_even_with_a_valid_cache(
    client, system_headers, k8s_client, kit, switch
):
    change, needs_project = REFUSALS[switch]
    use_secret(k8s_client, **GITHUB_KEYS, **cache_of(kit.repo, kit.permission, "cached", now() + timedelta(hours=1)))
    project_id = kit.project.id
    change(kit)
    db.session.commit()

    bodies = [{"project_id": project_id}] if needs_project else [{}, {"project_id": project_id}]
    with responses.RequestsMock():  # no provider is called
        for body in bodies:
            response = client.post(kit.url, json=body, headers=system_headers)
            assert response.status_code == 403, (body, response.json)
    # Refused before the secret is read, so a cached token is not served either
    k8s_client["read_namespaced_secret_mock"].assert_not_called()
    k8s_client["patch_namespaced_secret_mock"].assert_not_called()


@pytest.mark.parametrize("switch", ["project", "resource"])
def test_a_disabled_project_or_resource_still_gets_a_token(client, system_headers, kit, switch):
    """Switched off is not revoked: the results of a task that finished before are delivered while it is off."""
    setattr(kit.project if switch == "project" else kit.assignment, "enabled", False)
    db.session.commit()
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, GITHUB_TOKEN_URL, json=github_answer(), status=201)
        response = client.post(kit.url, json={"project_id": kit.project.id}, headers=system_headers)
    assert response.status_code == 200, response.json
    assert response.json["token"] == "ghs_installation"


@pytest.mark.parametrize("project_id", ["other", 999], ids=["a project without the repository", "unknown project"])
def test_a_project_without_the_repository_is_refused(client, system_headers, other_project, kit, project_id):
    project_id = other_project.id if project_id == "other" else project_id
    with responses.RequestsMock():
        response = client.post(kit.url, json={"project_id": project_id}, headers=system_headers)
    assert response.status_code == 403, response.json
