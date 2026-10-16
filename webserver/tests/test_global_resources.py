"""
Global resources (ADR 0019 section 11): /global/datasets, /global/secrets and the trigger/results
repositories. One table-driven test per resource kind and failure class, not per value.
"""
import pytest

from app.helpers.base_model import db

DS = "/global/datasets"
SEC = "/global/secrets"
TRIG = "/global/repositories/triggers"
RES = "/global/repositories/results"
REPO_KINDS = [(TRIG, "global_trigger_repo"), (RES, "global_results_repo")]


def repo_body(**fields):
    return {"uri": "github.com/org/new", "provider": "github", "secret_label": "test-creds", **fields}


def ds_body(**fields):
    return {"name": "NewDs", "host": "db", "port": 5432, "secret_label": "test-creds", **fields}


def secret_body(**fields):
    return {"label": "new-creds", "provider": "K8S", "values": {"TOKEN": "t"}, **fields}


def assert_error(response, status):
    assert response.status_code == status, response.json
    assert isinstance(response.json.get("error"), str) and response.json["error"]


def disable_secret(make_global_secret, label="off-creds"):
    secret = make_global_secret(label=label)
    secret.enabled = False
    db.session.commit()


# ---------------------------------------------------------------- repositories: create

@pytest.mark.parametrize("base,raw", [
    (TRIG, "https://GitHub.com/Org/NEW.git/"),  # scheme, case, .git and trailing slash are normalised away
    (RES, "  github.com/org/new/  "),
    (TRIG, "https://github.com:443/org/new"),  # default port dropped
])
def test_repo_uri_normalised_on_create(client, admin_headers, global_secret, base, raw):
    response = client.post(base, json=repo_body(uri=raw), headers=admin_headers)
    assert response.status_code == 201, response.json
    assert response.json["uri"] == "github.com/org/new"
    assert response.json["api_uri"] == "https://api.github.com"
    assert response.json["enabled"] is True


@pytest.mark.parametrize("base,variant", [(TRIG, "https://GITHUB.COM/ORG/NEW.git"), (RES, " github.com/org/new/ ")])
def test_repo_duplicate_is_409_after_normalisation(client, admin_headers, global_secret, base, variant):
    assert client.post(base, json=repo_body(), headers=admin_headers).status_code == 201
    assert_error(client.post(base, json=repo_body(uri=variant), headers=admin_headers), 409)


def test_repo_non_default_port_is_kept_and_distinct(client, admin_headers, global_secret):
    gitea = repo_body(uri="git.example.com:8443/org/new", provider="gitea")
    first = client.post(TRIG, json=gitea, headers=admin_headers)
    assert first.status_code == 201 and first.json["uri"] == "git.example.com:8443/org/new"
    other = client.post(TRIG, json={**gitea, "uri": "git.example.com/org/new"}, headers=admin_headers)
    assert other.status_code == 201
    assert other.json["api_uri"] == "https://git.example.com/api/v1"  # gitea default api is on the repo host


@pytest.mark.parametrize("base,body", [
    (TRIG, {"uri": "ssh://git@github.com/org/new.git"}),  # scheme not http(s)
    (TRIG, {"uri": "https://user:pw@github.com/org/new"}),  # credentials in the uri
    (RES, {"uri": "github.com/org"}),  # no repo path
    (RES, {"uri": "   "}),
    (TRIG, {"uri": 123}),
    (TRIG, {"uri": "github.com/org/" + "a" * 5000}),  # absurdly long, still a clean error
    (TRIG, {"provider": "GitHub "}),
    (RES, {"provider": 5}),
    (TRIG, {"secret_label": ""}),
    (RES, {"secret_label": 5}),
    (TRIG, {"secret_label": "nope"}),
    (RES, {"enabled": "yes"}),
    (TRIG, {"api_uri": "https://evil.example.com"}),  # api_uri must be on the repo's own api host
    (RES, {"api_uri": "https://user:pw@api.github.com"}),
    (TRIG, {"username": "u"}),  # unknown fields are refused, not ignored
    (RES, {"bogus": "x"}),
])
def test_repo_create_invalid(client, admin_headers, global_secret, base, body):
    assert_error(client.post(base, json=repo_body(**body), headers=admin_headers), 400)


@pytest.mark.parametrize("base", [TRIG, RES])
def test_repo_create_missing_field_is_400(client, admin_headers, global_secret, base):
    for missing in ("uri", "provider", "secret_label"):
        body = repo_body()
        del body[missing]
        response = client.post(base, json=body, headers=admin_headers)
        assert_error(response, 400)
        assert missing in response.json["error"]


def test_repo_custom_api_uri_on_repo_host_accepted(client, admin_headers, global_secret):
    response = client.post(
        TRIG, json=repo_body(uri="git.example.com/org/new", provider="gitea", api_uri="https://git.example.com/x/api"),
        headers=admin_headers)
    assert response.status_code == 201, response.json
    assert response.json["api_uri"] == "https://git.example.com/x/api"


# ---------------------------------------------------------------- repositories: patch

@pytest.mark.parametrize("body", [
    {}, {"bogus": 1}, {"uri": "github.com/org/other"},  # empty, unknown and immutable fields
    {"provider": "bogus"}, {"api_uri": "https://evil.example.com"}, {"enabled": "false"},
    {"secret_label": "nope"}, {"secret_label": ""},
])
def test_repo_patch_invalid(client, admin_headers, global_trigger_repo, body):
    assert_error(client.patch(f"{TRIG}/{global_trigger_repo.id}", json=body, headers=admin_headers), 400)


@pytest.mark.parametrize("base,make", REPO_KINDS)
def test_repo_patch_enabled_secret_and_disabled_own_secret(
        client, admin_headers, request, make_global_secret, base, make):
    repo = request.getfixturevalue(make)
    url = f"{base}/{repo.id}"
    assert client.patch(url, json={"enabled": False}, headers=admin_headers).json["enabled"] is False
    make_global_secret(label="other-creds")
    moved = client.patch(url, json={"enabled": True, "secret_label": "other-creds"}, headers=admin_headers)
    assert moved.status_code == 200 and moved.json["secret"]["label"] == "other-creds"
    # keeping the repo's own secret is fine even once that secret is disabled
    repo.secret.enabled = False
    db.session.commit()
    assert client.patch(url, json={"secret_label": "other-creds"}, headers=admin_headers).status_code == 200


@pytest.mark.parametrize("url,body", [(TRIG, repo_body), (DS, ds_body)])
def test_create_referencing_disabled_secret_is_400(client, admin_headers, make_global_secret, url, body):
    disable_secret(make_global_secret)
    assert_error(client.post(url, json=body(secret_label="off-creds"), headers=admin_headers), 400)


# ---------------------------------------------------------------- datasets

def test_dataset_create_lowercases_and_unquotes_name(client, admin_headers, global_secret):
    response = client.post(DS, json=ds_body(name="My%20DS"), headers=admin_headers)
    assert response.status_code == 201, response.json
    assert response.json["name"] == "my ds"
    assert response.json["enabled"] is True
    assert response.json["secret"]["label"] == "test-creds"


def test_dataset_duplicate_name_is_409_case_insensitive(client, admin_headers, global_secret):
    assert client.post(DS, json=ds_body(), headers=admin_headers).status_code == 201
    assert_error(client.post(DS, json=ds_body(name="NEWDS"), headers=admin_headers), 409)


@pytest.mark.parametrize("body", [
    {"name": ""}, {"name": 5}, {"name": "a" * 300},  # empty, wrong type, too long
    {"host": 5}, {"port": "5432"}, {"port": True}, {"port": 70000},
    {"type": "nosql"}, {"enabled": "true"}, {"dictionaries": "x"},
    {"secret_label": "nope"}, {"secret_label": ""},
    {"username": "u"}, {"project_id": 1},  # credentials and project are refused
])
def test_dataset_create_invalid(client, admin_headers, global_secret, body):
    assert_error(client.post(DS, json=ds_body(**body), headers=admin_headers), 400)


def test_dataset_create_missing_required_field_is_400(client, admin_headers, global_secret):
    for missing in ("name", "host", "port", "secret_label"):  # secret_label is required: no inline credentials
        body = ds_body()
        del body[missing]
        assert_error(client.post(DS, json=body, headers=admin_headers), 400)
    assert_error(client.post(DS, json={}, headers=admin_headers), 400)


def test_dataset_get_list_and_404(client, admin_headers, global_dataset):
    listing = client.get(DS, headers=admin_headers)
    assert listing.status_code == 200 and listing.json["total"] == 1
    assert listing.json["items"][0]["id"] == global_dataset.id
    assert client.get(f"{DS}/{global_dataset.id}", headers=admin_headers).json["name"] == "globalds"
    assert_error(client.get(f"{DS}/999", headers=admin_headers), 404)


def test_dataset_linked_needs_lock_to_patch_and_delete(client, admin_headers, linked_dataset, project):
    url = f"{DS}/{linked_dataset['dataset']['id']}"
    assert_error(client.patch(url, json={"host": "new"}, headers=admin_headers), 409)
    assert_error(client.delete(url, headers=admin_headers), 409)
    project.locked = True
    db.session.commit()
    patched = client.patch(url, json={"host": "new"}, headers=admin_headers)
    assert patched.status_code == 200 and patched.json["host"] == "new"
    assert client.delete(url, headers=admin_headers).status_code == 204


@pytest.mark.parametrize("body", [
    {}, {"bogus": 1}, {"project_id": 1}, {"port": None}, {"type": "nosql"}, {"enabled": "no"}, {"secret_label": "nope"},
])
def test_dataset_patch_invalid(client, admin_headers, global_dataset, body):
    assert_error(client.patch(f"{DS}/{global_dataset.id}", json=body, headers=admin_headers), 400)


def test_dataset_patch_name_secret_and_disabled_secret(
        client, admin_headers, global_dataset, make_global_dataset, make_global_secret):
    make_global_dataset(name="Second")
    url = f"{DS}/{global_dataset.id}"
    assert_error(client.patch(url, json={"name": "SECOND"}, headers=admin_headers), 409)
    make_global_secret(label="other-creds")
    ok = client.patch(url, json={"name": "Renamed", "enabled": False, "secret_label": "other-creds"},
                      headers=admin_headers)
    assert ok.status_code == 200, ok.json
    assert ok.json["name"] == "renamed" and ok.json["enabled"] is False
    assert ok.json["secret"]["label"] == "other-creds"
    disable_secret(make_global_secret)
    assert_error(client.patch(url, json={"secret_label": "off-creds"}, headers=admin_headers), 400)
    # keeping its own secret is allowed even once that secret is disabled
    global_dataset.secret.enabled = False
    db.session.commit()
    kept = client.patch(url, json={"secret_label": global_dataset.secret.label, "host": "newhost"}, headers=admin_headers)
    assert kept.status_code == 200 and kept.json["host"] == "newhost"


# ---------------------------------------------------------------- secrets

def test_secret_create_hides_values_and_duplicate_is_409(client, admin_headers, k8s_client):
    response = client.post(SEC, json=secret_body(description="déscription"), headers=admin_headers)
    assert response.status_code == 201, response.json
    assert response.json["label"] == "new-creds" and response.json["key"] == "fn-secret-new-creds"
    assert "values" not in response.json and "TOKEN" not in str(response.json)
    assert k8s_client["create_namespaced_secret_mock"].called
    assert_error(client.post(SEC, json=secret_body(), headers=admin_headers), 409)


@pytest.mark.parametrize("label", ["a.b-1", "0lead", "x" * 200])
def test_secret_label_valid_forms(client, admin_headers, k8s_client, label):
    response = client.post(SEC, json=secret_body(label=label), headers=admin_headers)
    assert response.status_code == 201, response.json
    assert client.get(f"{SEC}/{label}", headers=admin_headers).status_code == 200


@pytest.mark.parametrize("body", [
    {"label": "Upper"}, {"label": "sl/ash"}, {"label": "éclair"}, {"label": "a" * 250},  # not slug safe / too long
    {"label": ""}, {"label": 5},
    {"provider": "k8s"}, {"provider": "NOPE"},
    {"values": {}}, {"values": "x"}, {"values": {"TOKEN": ""}}, {"values": {"bad key": "v"}},
    {"enabled": "yes"},
])
def test_secret_create_invalid(client, admin_headers, k8s_client, body):
    assert_error(client.post(SEC, json=secret_body(**body), headers=admin_headers), 400)
    assert not k8s_client["create_namespaced_secret_mock"].called


def test_secret_create_missing_field_is_400(client, admin_headers, k8s_client):
    for missing in ("label", "provider", "values"):
        body = secret_body()
        del body[missing]
        assert_error(client.post(SEC, json=body, headers=admin_headers), 400)


def test_secret_list_get_and_404(client, admin_headers, k8s_client, global_secret):
    assert [s["label"] for s in client.get(SEC, headers=admin_headers).json] == ["test-creds"]
    assert client.get(f"{SEC}/test-creds", headers=admin_headers).status_code == 200
    for method in ("get", "patch", "delete"):
        assert_error(getattr(client, method)(f"{SEC}/nope", json={"enabled": False}, headers=admin_headers), 404)


def test_secret_rotate_and_disable(client, admin_headers, k8s_client, global_secret):
    rotated = client.patch(f"{SEC}/test-creds", json={"values": {"TOKEN": "t2"}}, headers=admin_headers)
    assert rotated.status_code == 200
    assert k8s_client["create_namespaced_secret_mock"].called
    both = client.patch(f"{SEC}/test-creds", json={"enabled": False, "values": {"TOKEN": "n"}}, headers=admin_headers)
    assert both.status_code == 200 and both.json["enabled"] is False
    assert client.patch(f"{SEC}/test-creds", json={"enabled": True}, headers=admin_headers).json["enabled"] is True


@pytest.mark.parametrize("body", [
    {}, {"bogus": 1}, {"label": "renamed", "values": {"TOKEN": "t"}},  # label is immutable, not ignored
    {"values": {"bad key": "v"}}, {"enabled": "no"},
])
def test_secret_patch_invalid(client, admin_headers, k8s_client, global_secret, body):
    assert_error(client.patch(f"{SEC}/test-creds", json=body, headers=admin_headers), 400)


@pytest.mark.parametrize("make", ["global_dataset", "global_trigger_repo", "global_results_repo"])
def test_secret_in_use_cannot_be_deleted(client, admin_headers, k8s_client, request, make):
    request.getfixturevalue(make)
    assert_error(client.delete(f"{SEC}/test-creds", headers=admin_headers), 409)
    assert not k8s_client["delete_namespaced_secret_mock"].called


def test_secret_delete_once_unused_and_repointing_frees_it(
        client, admin_headers, k8s_client, global_trigger_repo, make_global_secret):
    make_global_secret(label="other-creds")
    assert client.patch(f"{TRIG}/{global_trigger_repo.id}", json={"secret_label": "other-creds"},
                        headers=admin_headers).status_code == 200
    assert_error(client.delete(f"{SEC}/other-creds", headers=admin_headers), 409)
    assert client.delete(f"{SEC}/test-creds", headers=admin_headers).status_code == 204
    assert k8s_client["delete_namespaced_secret_mock"].called
    assert_error(client.get(f"{SEC}/test-creds", headers=admin_headers), 404)


def test_linked_secret_enabled_flag_needs_lock_but_rotation_does_not(client, admin_headers, k8s_client, linked_secret):
    assert client.patch(f"{SEC}/test-creds", json={"values": {"TOKEN": "n"}}, headers=admin_headers).status_code == 200
    assert_error(client.patch(f"{SEC}/test-creds", json={"enabled": False}, headers=admin_headers), 409)


# ---------------------------------------------------------------- delete, ids and HTTP edges

def test_unused_resources_delete_204_then_404(client, admin_headers, global_dataset, global_trigger_repo,
                                              global_results_repo):
    for base, rid in [(DS, global_dataset.id), (TRIG, global_trigger_repo.id), (RES, global_results_repo.id)]:
        assert client.delete(f"{base}/{rid}", headers=admin_headers).status_code == 204
        assert_error(client.get(f"{base}/{rid}", headers=admin_headers), 404)


def test_linked_repo_needs_lock_to_delete_or_disable(client, admin_headers, linked_trigger_repo, global_trigger_repo,
                                                     make_trigger_repo):
    url = f"{TRIG}/{global_trigger_repo.id}"
    assert_error(client.delete(url, headers=admin_headers), 409)
    assert_error(client.patch(url, json={"enabled": False}, headers=admin_headers), 409)
    unlinked = make_trigger_repo(uri="github.com/org/unlinked")
    assert client.patch(f"{TRIG}/{unlinked.id}", json={"enabled": False}, headers=admin_headers).status_code == 200


@pytest.mark.parametrize("bad_id", ["abc", "1.5", "0", "999999", str(2**63)])  # non-integer, unknown, out of range
def test_non_integer_or_unknown_id_is_404(client, admin_headers, bad_id):
    for base in (DS, TRIG, RES):
        for method in ("get", "patch", "delete"):
            assert_error(getattr(client, method)(f"{base}/{bad_id}", json={"enabled": True}, headers=admin_headers), 404)


def test_methods_bodies_and_empty_lists(client, admin_headers, global_dataset):
    for url in (DS, SEC, TRIG, RES):
        for method in ("put", "delete", "patch"):
            assert_error(getattr(client, method)(url, json={}, headers=admin_headers), 405)
        assert_error(client.post(url, data="[1, 2]", headers=admin_headers), 400)  # non-object JSON
        malformed = client.post(url, data="{not json", headers=admin_headers)
        assert 400 <= malformed.status_code < 500 and "error" in malformed.json
    assert_error(client.put(f"{DS}/{global_dataset.id}", json={}, headers=admin_headers), 405)
    for url in (DS, SEC, TRIG, RES):
        body = client.get(url + "/", headers=admin_headers).json  # trailing slash works
        items = body if isinstance(body, list) else body["items"]
        assert len(items) == (1 if url in (DS, SEC) else 0)  # the dataset fixture brings its secret
