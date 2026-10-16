"""
Deep validation and edge-case tests for the global resources (ADR 0019 section 11):
/global/datasets, /global/secrets, /global/repositories/triggers, /global/repositories/results.
"""
import pytest

from app.helpers.base_model import db

DS = "/global/datasets"
SEC = "/global/secrets"
TRIG = "/global/repositories/triggers"
RES = "/global/repositories/results"
REPO_BASES = [TRIG, RES]


def repo_body(**fields):
    body = {"uri": "github.com/org/new", "provider": "github", "secret_label": "test-creds"}
    body.update(fields)
    return body


def ds_body(**fields):
    body = {"name": "NewDs", "host": "db", "port": 5432, "secret_label": "test-creds"}
    body.update(fields)
    return body


def secret_body(**fields):
    body = {"label": "new-creds", "provider": "K8S", "values": {"TOKEN": "t"}}
    body.update(fields)
    return body


def assert_error(response, status):
    assert response.status_code == status, response.json
    assert isinstance(response.json, dict)
    assert isinstance(response.json.get("error"), str) and response.json["error"]


# ---------------------------------------------------------------- repository uri normalisation

@pytest.mark.parametrize("base", REPO_BASES)
@pytest.mark.parametrize("raw", [
    "https://github.com/org/new",
    "http://github.com/org/new",
    "github.com/org/new/",
    "github.com/org/new.git",
    "https://github.com/org/new.git/",
    "  github.com/org/new  ",
    "GitHub.com/Org/NEW",
    "https://github.com:443/org/new",
])
def test_repo_uri_is_normalised_on_create(client, admin_headers, global_secret, base, raw):
    response = client.post(base, json=repo_body(uri=raw), headers=admin_headers)
    assert response.status_code == 201, response.json
    assert response.json["uri"] == "github.com/org/new"
    assert response.json["api_uri"] == "https://api.github.com"


@pytest.mark.parametrize("base", REPO_BASES)
@pytest.mark.parametrize("variant", [
    "https://github.com/org/new/", "GITHUB.COM/ORG/NEW", "github.com/org/new.git", " github.com/org/new ",
])
def test_repo_duplicate_detected_after_normalisation(client, admin_headers, global_secret, base, variant):
    assert client.post(base, json=repo_body(), headers=admin_headers).status_code == 201
    assert_error(client.post(base, json=repo_body(uri=variant), headers=admin_headers), 409)


@pytest.mark.parametrize("base", REPO_BASES)
def test_repo_non_default_port_is_kept_and_distinct(client, admin_headers, global_secret, base):
    first = client.post(base, json=repo_body(uri="git.example.com:8443/org/new", provider="gitea"),
                        headers=admin_headers)
    assert first.status_code == 201, first.json
    assert first.json["uri"] == "git.example.com:8443/org/new"
    other = client.post(base, json=repo_body(uri="git.example.com/org/new", provider="gitea"),
                        headers=admin_headers)
    assert other.status_code == 201, other.json


@pytest.mark.parametrize("base", REPO_BASES)
@pytest.mark.parametrize("bad_uri", [
    "git@github.com:org/new.git",
    "ssh://git@github.com/org/new.git",
    "ftp://github.com/org/new",
    "https://user:pw@github.com/org/new",
    "github.com",
    "github.com/org",
    "https://",
    "   ",
    "github.com:notaport/org/new",
])
def test_repo_bad_uri_is_400(client, admin_headers, global_secret, base, bad_uri):
    assert_error(client.post(base, json=repo_body(uri=bad_uri), headers=admin_headers), 400)


@pytest.mark.parametrize("base", REPO_BASES)
@pytest.mark.parametrize("field,value", [
    ("uri", 123), ("uri", None), ("uri", ["github.com/org/new"]), ("uri", ""),
    ("provider", 5), ("provider", ""), ("provider", "GitHub "),
    ("secret_label", 5),
    ("secret_label", ""), ("secret_label", None),
    ("enabled", "yes"), ("enabled", 1), ("enabled", None),
    ("api_uri", 5),
])
def test_repo_create_wrong_typed_or_empty_fields(client, admin_headers, global_secret, base, field, value):
    response = client.post(base, json=repo_body(**{field: value}), headers=admin_headers)
    assert_error(response, 400)


@pytest.mark.parametrize("base", REPO_BASES)
@pytest.mark.parametrize("missing", ["uri", "provider", "secret_label"])
def test_repo_create_missing_field(client, admin_headers, global_secret, base, missing):
    body = repo_body()
    del body[missing]
    response = client.post(base, json=body, headers=admin_headers)
    assert_error(response, 400)
    assert missing in response.json["error"]


@pytest.mark.parametrize("base", [
    b
    for b in REPO_BASES])
def test_repo_create_unknown_field_is_not_silently_accepted(client, admin_headers, global_secret, base):
    response = client.post(base, json=repo_body(bogus="x"), headers=admin_headers)
    assert_error(response, 400)


@pytest.mark.parametrize("base", [
    b
    for b in REPO_BASES])
def test_repo_very_long_uri_is_not_a_500(client, admin_headers, global_secret, base):
    uri = "github.com/org/" + "a" * 5000
    response = client.post(base, json=repo_body(uri=uri), headers=admin_headers)
    assert response.status_code in (400, 413), response.json


@pytest.mark.parametrize("base", REPO_BASES)
def test_repo_unicode_and_special_characters_in_uri(client, admin_headers, global_secret, base):
    response = client.post(base, json=repo_body(uri="github.com/org/repö-中文"), headers=admin_headers)
    assert response.status_code in (201, 400), response.json
    assert response.status_code != 500
    if response.status_code == 400:
        assert_error(response, 400)


# ---------------------------------------------------------------- api_uri

@pytest.mark.parametrize("base", REPO_BASES)
def test_gitea_default_api_uri_is_on_repo_host(client, admin_headers, global_secret, base):
    response = client.post(base, json=repo_body(uri="git.example.com/org/new", provider="gitea"),
                           headers=admin_headers)
    assert response.status_code == 201, response.json
    assert response.json["api_uri"] == "https://git.example.com/api/v1"


@pytest.mark.parametrize("base", REPO_BASES)
def test_github_default_api_uri_ignores_repo_host(client, admin_headers, global_secret, base):
    response = client.post(base, json=repo_body(uri="ghe.example.com/org/new"), headers=admin_headers)
    assert response.status_code in (201, 400), response.json
    if response.status_code == 201:
        assert response.json["api_uri"] == "https://api.github.com"


@pytest.mark.parametrize("base", REPO_BASES)
@pytest.mark.parametrize("api_uri", [
    "https://evil.example.com",
    "ftp://api.github.com",
    "https://user:pw@api.github.com",
    "api.github.com",
    "https://github.com.evil.com",
])
def test_api_uri_on_other_host_or_bad_scheme_refused(client, admin_headers, global_secret, base, api_uri):
    assert_error(client.post(base, json=repo_body(api_uri=api_uri), headers=admin_headers), 400)


@pytest.mark.parametrize("base", REPO_BASES)
def test_api_uri_custom_on_repo_host_accepted(client, admin_headers, global_secret, base):
    response = client.post(
        base, json=repo_body(uri="git.example.com/org/new", provider="gitea",
                             api_uri="https://git.example.com/custom/api"),
        headers=admin_headers)
    assert response.status_code == 201, response.json
    assert response.json["api_uri"] == "https://git.example.com/custom/api"


@pytest.mark.parametrize("base,make", [(TRIG, "global_trigger_repo"), (RES, "global_results_repo")])
@pytest.mark.parametrize("body,status", [
    ({"api_uri": "https://evil.example.com"}, 400),
    ({"api_uri": ""}, 400),
    ({"api_uri": 5}, 400),
    ({"provider": "bogus"}, 400),
    ({"provider": ""}, 400),
    ({"provider": 5}, 400),
    ({"enabled": "false"}, 400),
    ({"enabled": 0}, 400),
    ({"secret_label": ""}, 400),
    ({"secret_label": "nope"}, 400),
    ({"uri": "github.com/org/other"}, 400),
    ({"bogus": 1}, 400),
    ({}, 400),
])
def test_repo_patch_invalid_bodies(client, admin_headers, request, base, make, body, status):
    repo = request.getfixturevalue(make)
    assert_error(client.patch(f"{base}/{repo.id}", json=body, headers=admin_headers), status)


@pytest.mark.parametrize("base,make", [(TRIG, "global_trigger_repo"), (RES, "global_results_repo")])
def test_repo_patch_provider_and_enabled_toggle(client, admin_headers, request, base, make):
    repo = request.getfixturevalue(make)
    response = client.patch(f"{base}/{repo.id}", json={"provider": "gitea", "api_uri": "https://github.com"},
                            headers=admin_headers)
    # github.com host repo + gitea provider: api_uri must be on api.github.com
    assert_error(response, 400)
    off = client.patch(f"{base}/{repo.id}", json={"enabled": False}, headers=admin_headers)
    assert off.status_code == 200 and off.json["enabled"] is False
    on = client.patch(f"{base}/{repo.id}", json={"enabled": True}, headers=admin_headers)
    assert on.status_code == 200 and on.json["enabled"] is True


def test_repo_create_disabled_and_list_shows_flag(client, admin_headers, global_secret):
    created = client.post(TRIG, json=repo_body(enabled=False), headers=admin_headers)
    assert created.status_code == 201 and created.json["enabled"] is False
    assert client.get(f"{TRIG}/{created.json['id']}", headers=admin_headers).json["enabled"] is False


# ---------------------------------------------------------------- secret_label references

@pytest.mark.parametrize("base,make", [(TRIG, "global_trigger_repo"), (RES, "global_results_repo")])
def test_repo_patch_secret_label_to_other_secret(client, admin_headers, request, make_global_secret, base, make):
    repo = request.getfixturevalue(make)
    make_global_secret(label="other-creds")
    response = client.patch(f"{base}/{repo.id}", json={"secret_label": "other-creds"}, headers=admin_headers)
    assert response.status_code == 200, response.json
    assert response.json["secret"]["label"] == "other-creds"


def test_referencing_disabled_secret_on_create(client, admin_headers, make_global_secret):
    secret = make_global_secret(label="off-creds")
    secret.enabled = False
    db.session.commit()
    response = client.post(TRIG, json=repo_body(secret_label="off-creds"), headers=admin_headers)
    assert_error(response, 400)


@pytest.mark.parametrize("url,body", [
    (TRIG, lambda: repo_body(secret_label="off-creds")),
    (RES, lambda: repo_body(secret_label="off-creds")),
    (DS, lambda: ds_body(secret_label="off-creds")),
])
def test_referencing_disabled_secret_is_refused(client, admin_headers, make_global_secret, url, body):
    secret = make_global_secret(label="off-creds")
    secret.enabled = False
    db.session.commit()
    assert_error(client.post(url, json=body(), headers=admin_headers), 400)


def test_dataset_patch_to_disabled_secret_is_refused(client, admin_headers, global_dataset, make_global_secret):
    secret = make_global_secret(label="off-creds")
    secret.enabled = False
    db.session.commit()
    assert_error(client.patch(f"{DS}/{global_dataset.id}", json={"secret_label": "off-creds"},
                              headers=admin_headers), 400)


@pytest.mark.parametrize("base,make", [(TRIG, "global_trigger_repo"), (RES, "global_results_repo")])
def test_repo_patch_keeping_disabled_secret_is_allowed(client, admin_headers, request, base, make):
    repo = request.getfixturevalue(make)
    label = repo.secret.label
    repo.secret.enabled = False
    db.session.commit()
    response = client.patch(f"{base}/{repo.id}", json={"secret_label": label}, headers=admin_headers)
    assert response.status_code == 200, response.json


def test_dataset_patch_keeping_disabled_secret_is_allowed(client, admin_headers, global_dataset, global_secret):
    global_dataset.secret.enabled = False
    db.session.commit()
    response = client.patch(f"{DS}/{global_dataset.id}",
                            json={"secret_label": global_dataset.secret.label, "host": "newhost"},
                            headers=admin_headers)
    assert response.status_code == 200, response.json
    assert response.json["host"] == "newhost"


# ---------------------------------------------------------------- datasets

def test_dataset_name_stored_lowercase_and_unquoted(client, admin_headers, global_secret):
    response = client.post(DS, json=ds_body(name="My%20DS"), headers=admin_headers)
    assert response.status_code == 201, response.json
    assert response.json["name"] == "my ds"


@pytest.mark.parametrize("second", ["NewDs", "newds", "NEWDS"])
def test_dataset_duplicate_name_is_409_case_insensitive(client, admin_headers, global_secret, second):
    assert client.post(DS, json=ds_body(), headers=admin_headers).status_code == 201
    assert_error(client.post(DS, json=ds_body(name=second), headers=admin_headers), 409)


def test_dataset_slug_collision_names_are_distinct(client, admin_headers, global_secret):
    first = client.post(DS, json=ds_body(name="a b"), headers=admin_headers)
    second = client.post(DS, json=ds_body(name="a-b"), headers=admin_headers)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json["id"] != second.json["id"]


@pytest.mark.parametrize("name", ["déjà vu", "中文", "with/slash", "semi;colon", "q'uote", "a" * 200])
def test_dataset_special_character_names_are_not_500(client, admin_headers, global_secret, name):
    response = client.post(DS, json=ds_body(name=name), headers=admin_headers)
    assert response.status_code in (201, 400), response.json
    if response.status_code == 201:
        assert response.json["name"] == name.lower()
        assert client.get(f"{DS}/{response.json['id']}", headers=admin_headers).status_code == 200


def test_dataset_very_long_name_is_400_not_500(client, admin_headers, global_secret):
    assert_error(client.post(DS, json=ds_body(name="a" * 300), headers=admin_headers), 400)


@pytest.mark.parametrize("field,value", [
    ("name", ""), ("name", None), ("name", 5), ("name", ["x"]),
    ("host", ""), ("host", None), ("host", 5),
    ("port", "5432"), ("port", None), ("port", 1.5), ("port", True), ("port", -1), ("port", 70000),
    ("type", "nosql"), ("type", 5),
    ("enabled", "true"), ("enabled", 1),
    ("secret_label", ""), ("secret_label", "nope"), ("secret_label", 5),
    ("dictionaries", "x"),
])
def test_dataset_create_invalid_fields(client, admin_headers, global_secret, field, value):
    assert_error(client.post(DS, json=ds_body(**{field: value}), headers=admin_headers), 400)


@pytest.mark.parametrize("missing", ["name", "host", "port", "secret_label"])
def test_dataset_create_missing_required(client, admin_headers, global_secret, missing):
    body = ds_body()
    del body[missing]
    assert_error(client.post(DS, json=body, headers=admin_headers), 400)


def test_dataset_create_empty_body(client, admin_headers, global_secret):
    assert_error(client.post(DS, json={}, headers=admin_headers), 400)


@pytest.mark.parametrize("body", [
    {"bogus": 1}, {"port": "x"}, {"port": None}, {"enabled": "no"}, {"secret_label": "nope"},
    {"secret_label": ""},
    {"type": "nosql"},
    {"project_id": 1}, {"dictionaries": "x"},
])
def test_dataset_patch_invalid_bodies(client, admin_headers, global_dataset, body):
    assert_error(client.patch(f"{DS}/{global_dataset.id}", json=body, headers=admin_headers), 400)


def test_dataset_patch_name_case_and_duplicate(client, admin_headers, global_dataset, make_global_dataset):
    make_global_dataset(name="Second")
    renamed = client.patch(f"{DS}/{global_dataset.id}", json={"name": "Renamed"}, headers=admin_headers)
    assert renamed.status_code == 200, renamed.json
    assert renamed.json["name"] == "renamed"


def test_dataset_patch_rename_to_existing_name_is_409(client, admin_headers, global_dataset, make_global_dataset):
    make_global_dataset(name="Second")
    assert_error(client.patch(f"{DS}/{global_dataset.id}", json={"name": "SECOND"}, headers=admin_headers), 409)


def test_dataset_patch_enabled_and_secret_label(client, admin_headers, global_dataset, make_global_secret):
    make_global_secret(label="other-creds")
    response = client.patch(f"{DS}/{global_dataset.id}", json={"enabled": False, "secret_label": "other-creds"},
                            headers=admin_headers)
    assert response.status_code == 200, response.json
    assert response.json["enabled"] is False
    assert response.json["secret"]["label"] == "other-creds"


def test_dataset_patch_empty_body_is_not_500(client, admin_headers, global_dataset):
    response = client.patch(f"{DS}/{global_dataset.id}", json={}, headers=admin_headers)
    assert response.status_code in (200, 400), response.json


# ---------------------------------------------------------------- secrets

@pytest.mark.parametrize("label", [
    "Upper", "has space", "under_score", "trailing-", "dot..dot", "sl/ash", "q?mark",
    "éclair", "中文", "semi;colon", "per%cent", " padded", "a" * 250,
])
def test_secret_label_must_be_slug_safe(client, admin_headers, k8s_client, label):
    assert_error(client.post(SEC, json=secret_body(label=label), headers=admin_headers), 400)
    assert not k8s_client["create_namespaced_secret_mock"].called


@pytest.mark.parametrize("label", ["a", "abc-123", "a.b", "x" * 200, "0lead", "-leading"])
def test_secret_label_valid_forms(client, admin_headers, k8s_client, label):
    response = client.post(SEC, json=secret_body(label=label), headers=admin_headers)
    assert response.status_code == 201, response.json
    assert response.json["label"] == label
    assert response.json["key"] == f"fn-secret-{label}"
    assert client.get(f"{SEC}/{label}", headers=admin_headers).status_code == 200


@pytest.mark.parametrize("body", [
    {"label": ""}, {"label": None}, {"label": 5}, {"label": ["x"]},
    {"provider": "k8s"}, {"provider": ""}, {"provider": None}, {"provider": 1},
    {"values": {}}, {"values": None}, {"values": "x"}, {"values": ["x"]},
    {"values": {"TOKEN": ""}}, {"values": {"TOKEN": 5}}, {"values": {"bad key": "v"}}, {"values": {"": "v"}},
    {"values": {"TOKEN": None}}, {"enabled": "yes"}, {"enabled": 1},
])
def test_secret_create_invalid_fields(client, admin_headers, k8s_client, body):
    assert_error(client.post(SEC, json=secret_body(**body), headers=admin_headers), 400)
    assert not k8s_client["create_namespaced_secret_mock"].called


@pytest.mark.parametrize("missing", ["label", "provider", "values"])
def test_secret_create_missing_field(client, admin_headers, k8s_client, missing):
    body = secret_body()
    del body[missing]
    assert_error(client.post(SEC, json=body, headers=admin_headers), 400)


def test_secret_create_unicode_value_and_description(client, admin_headers, k8s_client):
    response = client.post(
        SEC, json=secret_body(values={"TOKEN": "päss中"}, description="déscription \U0001f511"),
        headers=admin_headers)
    assert response.status_code == 201, response.json
    assert "values" not in response.json
    assert "päss" not in str(response.json)


def test_secret_label_is_case_sensitive_distinct_from_existing(client, admin_headers, k8s_client, global_secret):
    # "TEST-CREDS" is not a valid label at all, so it cannot shadow "test-creds"
    assert_error(client.post(SEC, json=secret_body(label="TEST-CREDS"), headers=admin_headers), 400)


@pytest.mark.parametrize("body", [
    {}, {"values": {}}, {"values": "x"}, {"values": {"TOKEN": ""}}, {"values": {"bad key": "v"}},
    {"enabled": "no"}, {"enabled": None}, {"enabled": 0},
])
def test_secret_patch_invalid_bodies(client, admin_headers, k8s_client, global_secret, body):
    assert_error(client.patch(f"{SEC}/test-creds", json=body, headers=admin_headers), 400)


def test_secret_patch_unknown_field_only(client, admin_headers, k8s_client, global_secret):
    response = client.patch(f"{SEC}/test-creds", json={"bogus": 1}, headers=admin_headers)
    assert_error(response, 400)


def test_secret_patch_label_is_not_silently_ignored(client, admin_headers, k8s_client, global_secret):
    response = client.patch(f"{SEC}/test-creds",
                            json={"label": "renamed", "values": {"TOKEN": "t"}}, headers=admin_headers)
    assert response.status_code == 400


def test_secret_disable_and_reenable(client, admin_headers, k8s_client, global_secret):
    off = client.patch(f"{SEC}/test-creds", json={"enabled": False}, headers=admin_headers)
    assert off.status_code == 200 and off.json["enabled"] is False
    assert not k8s_client["create_namespaced_secret_mock"].called
    on = client.patch(f"{SEC}/test-creds", json={"enabled": True}, headers=admin_headers)
    assert on.status_code == 200 and on.json["enabled"] is True


def test_secret_rotate_and_disable_in_one_patch(client, admin_headers, k8s_client, global_secret):
    response = client.patch(f"{SEC}/test-creds", json={"enabled": False, "values": {"TOKEN": "n"}},
                            headers=admin_headers)
    assert response.status_code == 200 and response.json["enabled"] is False
    assert k8s_client["create_namespaced_secret_mock"].called


def test_secret_patch_and_delete_unknown_label_404(client, admin_headers, k8s_client):
    assert_error(client.patch(f"{SEC}/nope", json={"enabled": False}, headers=admin_headers), 404)
    assert_error(client.delete(f"{SEC}/nope", headers=admin_headers), 404)
    assert_error(client.get(f"{SEC}/nope", headers=admin_headers), 404)


def test_secret_in_use_by_dataset_or_repo_cannot_be_deleted(client, admin_headers, k8s_client, global_dataset):
    response = client.delete(f"{SEC}/test-creds", headers=admin_headers)
    assert_error(response, 409)
    assert not k8s_client["delete_namespaced_secret_mock"].called
    assert client.get(f"{SEC}/test-creds", headers=admin_headers).status_code == 200


@pytest.mark.parametrize("make", ["global_trigger_repo", "global_results_repo"])
def test_secret_in_use_by_repo_conflicts(client, admin_headers, k8s_client, request, make):
    request.getfixturevalue(make)
    assert_error(client.delete(f"{SEC}/test-creds", headers=admin_headers), 409)


def test_secret_becomes_deletable_after_users_removed(client, admin_headers, k8s_client, global_trigger_repo):
    assert client.delete(f"{SEC}/test-creds", headers=admin_headers).status_code == 409
    assert client.delete(f"{TRIG}/{global_trigger_repo.id}", headers=admin_headers).status_code == 204
    assert client.delete(f"{SEC}/test-creds", headers=admin_headers).status_code == 204
    assert client.get(f"{SEC}/test-creds", headers=admin_headers).status_code == 404


def test_secret_repointed_repo_frees_old_secret(client, admin_headers, k8s_client, global_trigger_repo,
                                                make_global_secret):
    make_global_secret(label="other-creds")
    assert client.patch(f"{TRIG}/{global_trigger_repo.id}", json={"secret_label": "other-creds"},
                        headers=admin_headers).status_code == 200
    assert client.delete(f"{SEC}/test-creds", headers=admin_headers).status_code == 204
    assert client.delete(f"{SEC}/other-creds", headers=admin_headers).status_code == 409


# ---------------------------------------------------------------- deleting resources in use

def test_unused_resources_delete_204_then_404(client, admin_headers, global_dataset, global_trigger_repo,
                                              global_results_repo):
    for base, rid in [(DS, global_dataset.id), (TRIG, global_trigger_repo.id), (RES, global_results_repo.id)]:
        assert client.delete(f"{base}/{rid}", headers=admin_headers).status_code == 204
        assert_error(client.get(f"{base}/{rid}", headers=admin_headers), 404)
        assert_error(client.delete(f"{base}/{rid}", headers=admin_headers), 404)


def test_linked_resources_cannot_be_deleted_while_project_unlocked(
        client, admin_headers, linked_dataset, linked_trigger_repo, global_dataset, global_trigger_repo):
    assert_error(client.delete(f"{DS}/{global_dataset.id}", headers=admin_headers), 409)
    assert_error(client.delete(f"{TRIG}/{global_trigger_repo.id}", headers=admin_headers), 409)
    assert client.get(f"{DS}/{global_dataset.id}", headers=admin_headers).status_code == 200


def test_disabling_linked_resource_needs_lock_but_not_when_unlinked(
        client, admin_headers, project, global_trigger_repo, make_trigger_repo, linked_trigger_repo):
    unlinked = make_trigger_repo(uri="github.com/org/unlinked")
    assert client.patch(f"{TRIG}/{unlinked.id}", json={"enabled": False}, headers=admin_headers).status_code == 200
    assert_error(client.patch(f"{TRIG}/{global_trigger_repo.id}", json={"enabled": False},
                              headers=admin_headers), 409)


def test_linked_secret_enabled_flag_needs_lock_but_rotation_does_not(
        client, admin_headers, k8s_client, linked_secret):
    assert client.patch(f"{SEC}/test-creds", json={"values": {"TOKEN": "n"}}, headers=admin_headers).status_code == 200
    assert_error(client.patch(f"{SEC}/test-creds", json={"enabled": False}, headers=admin_headers), 409)


def test_linked_secret_can_be_deleted_when_locked_and_unused(client, admin_headers, k8s_client, linked_secret,
                                                             lock_project):
    assert client.delete(f"{SEC}/test-creds", headers=admin_headers).status_code == 204


# ---------------------------------------------------------------- ids in URLs, methods, error shape

@pytest.mark.parametrize("base", [DS, TRIG, RES])
@pytest.mark.parametrize("bad_id", ["abc", "1.5", "-1x", "1;2", "%20", "0x1"])
@pytest.mark.parametrize("method", ["get", "patch", "delete"])
def test_non_integer_id_is_404_with_error_body(client, admin_headers, base, bad_id, method):
    response = getattr(client, method)(f"{base}/{bad_id}", json={"enabled": True}, headers=admin_headers)
    assert_error(response, 404)


@pytest.mark.parametrize("base", [DS, TRIG, RES])
@pytest.mark.parametrize("rid", [0, -1, 999999, 2**31, 2**63])
def test_integer_id_out_of_range_or_unknown_is_404(client, admin_headers, base, rid):
    for method in ("get", "delete"):
        response = getattr(client, method)(f"{base}/{rid}", headers=admin_headers)
        assert_error(response, 404)


@pytest.mark.parametrize("url,method", [
    (DS, "put"), (DS, "delete"), (DS, "patch"),
    (SEC, "put"), (SEC, "delete"), (SEC, "patch"),
    (TRIG, "put"), (TRIG, "delete"), (TRIG, "patch"),
    (RES, "put"), (RES, "delete"), (RES, "patch"),
])
def test_collection_method_not_allowed(client, admin_headers, url, method):
    assert_error(getattr(client, method)(url, json={}, headers=admin_headers), 405)


def test_item_method_not_allowed(client, admin_headers, global_dataset, global_trigger_repo,
                                 global_results_repo, global_secret):
    for url in (f"{DS}/{global_dataset.id}", f"{TRIG}/{global_trigger_repo.id}",
                f"{RES}/{global_results_repo.id}", f"{SEC}/test-creds"):
        for method in ("post", "put"):
            assert_error(getattr(client, method)(url, json={}, headers=admin_headers), 405)


@pytest.mark.parametrize("url", [DS, SEC, TRIG, RES])
def test_post_with_non_object_json_body_is_400(client, admin_headers, url):
    response = client.post(url, data="[1, 2]", headers=admin_headers)
    assert_error(response, 400)


@pytest.mark.parametrize("url", [DS, SEC, TRIG, RES])
def test_post_with_malformed_json_is_4xx_with_error_body(client, admin_headers, url):
    response = client.post(url, data="{not json", headers=admin_headers)
    assert 400 <= response.status_code < 500, response.json
    assert "error" in response.json


@pytest.mark.parametrize("url", [DS, SEC, TRIG, RES])
def test_unauthenticated_requests_are_refused(client, url):
    response = client.get(url)
    assert response.status_code in (401, 403)
    assert "error" in response.json


@pytest.mark.parametrize("url", [DS, SEC, TRIG, RES])
def test_list_is_empty_and_paths_with_trailing_slash_work(client, admin_headers, url):
    for path in (url, url + "/"):
        response = client.get(path, headers=admin_headers)
        assert response.status_code == 200
        body = response.json
        assert (body if isinstance(body, list) else body["items"]) == []
