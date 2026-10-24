"""
A disabled secret's value is moved to the quarantine namespace and back; deleting a secret needs its users
disabled; enabling a dataset or repository on a disabled or deleted secret is a 409. The Kubernetes
client is an in-memory store here, so that where a value is can be asserted.
"""
import base64
import json
from types import SimpleNamespace

import pytest
from kubernetes.client.exceptions import ApiException

from app.helpers.base_model import db
from app.helpers.const import QUARANTINE_NAMESPACE
from app.helpers.exceptions import InvalidRequest
from app.models.secret import Secret
from app.secrets_api import K8sSecretProvider

SEC = "/global/secrets"
DS = "/global/datasets"
TRIG = "/global/repositories/triggers"
RES = "/global/repositories/results"
NS = "default"
KEY = "fn-secret-test-creds"
Q = QUARANTINE_NAMESPACE
VALUE = {"TOKEN": base64.b64encode(b"t").decode()}
KINDS = [(DS, "global_dataset"), (TRIG, "global_trigger_repo"), (RES, "global_results_repo")]


@pytest.fixture
def store(k8s_client, global_secret) -> dict:
    """{(namespace, name): data} behind the mocked client, holding test-creds in its own namespace."""
    data = {(NS, KEY): dict(VALUE)}

    def read(name, namespace, **kwargs):
        if (namespace, name) not in data:
            raise ApiException(status=404)
        return SimpleNamespace(data=dict(data[(namespace, name)]))

    def create(namespace, body, **kwargs):
        if (namespace, body.metadata["name"]) in data:
            raise ApiException(status=409)
        data[(namespace, body.metadata["name"])] = dict(body.data)

    def patch(name, namespace, body, **kwargs):
        data[(namespace, name)] = {**data.get((namespace, name), {}), **body.data}

    def delete(name, namespace, **kwargs):
        if (namespace, name) not in data:
            raise ApiException(status=404)
        del data[(namespace, name)]

    k8s_client["read_namespaced_secret_mock"].side_effect = read
    k8s_client["create_namespaced_secret_mock"].side_effect = create
    k8s_client["patch_namespaced_secret_mock"].side_effect = patch
    k8s_client["delete_namespaced_secret_mock"].side_effect = delete
    global_secret.namespace = NS
    db.session.commit()
    return data


def secret_row() -> Secret:
    db.session.expire_all()
    return Secret.query.filter_by(label="test-creds").one()


def enabled_of(client, admin_headers, base, resource) -> bool:
    return client.get(f"{base}/{resource.id}", headers=admin_headers).json()["enabled"]


def patch(client, admin_headers, **body):
    return client.patch(f"{SEC}/test-creds", json=body, headers=admin_headers)


# ---------------------------------------------------------------- the move

def test_disabling_moves_the_value_and_enabling_moves_it_back_and_the_row_keeps_its_namespace(
        client, admin_headers, store):
    assert patch(client, admin_headers, enabled=False).status_code == 200
    assert store == {(Q, KEY): VALUE}
    assert secret_row().namespace == NS and secret_row().enabled is False

    assert patch(client, admin_headers, enabled=True).status_code == 200
    assert store == {(NS, KEY): VALUE}
    assert secret_row().namespace == NS and secret_row().enabled is True


def test_a_move_is_copy_then_delete_and_repeating_a_flip_touches_nothing(client, admin_headers, store, k8s_client):
    create, delete = k8s_client["create_namespaced_secret_mock"], k8s_client["delete_namespaced_secret_mock"]
    patch(client, admin_headers, enabled=False)
    assert create.call_args.args[0] == Q and delete.call_args.args == (KEY, NS)

    create.reset_mock()
    delete.reset_mock()
    assert patch(client, admin_headers, enabled=False).status_code == 200
    assert not create.called and not delete.called
    patch(client, admin_headers, enabled=True)
    create.reset_mock()
    delete.reset_mock()
    assert patch(client, admin_headers, enabled=True).status_code == 200
    assert not create.called and not delete.called
    assert store == {(NS, KEY): VALUE}


def test_the_provider_move_is_idempotent_and_copies_before_it_deletes(store, k8s_client):
    provider = K8sSecretProvider()
    provider.quarantine(KEY, NS)
    provider.quarantine(KEY, NS)  # already moved: nothing to read, nothing done
    assert store == {(Q, KEY): VALUE}
    provider.restore(KEY, NS)
    provider.restore(KEY, NS)
    assert store == {(NS, KEY): VALUE}

    # the delete after the copy fails: the value is in both places, not in neither
    k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(status=500)
    with pytest.raises(InvalidRequest):
        provider.quarantine(KEY, NS)
    assert store == {(NS, KEY): VALUE, (Q, KEY): VALUE}


def test_a_failing_move_leaves_the_database_unchanged(
        client, admin_headers, store, k8s_client, global_dataset, global_trigger_repo):
    working_create = k8s_client["create_namespaced_secret_mock"].side_effect
    k8s_client["create_namespaced_secret_mock"].side_effect = ApiException(
        status=500, reason="boom", http_resp=SimpleNamespace(
            status=500, reason="boom", data=json.dumps({"code": 500, "details": {"causes": []}}), getheaders=lambda: {}
        )
    )
    failed = patch(client, admin_headers, enabled=False)
    assert failed.status_code == 500
    assert secret_row().enabled is True
    assert enabled_of(client, admin_headers, DS, global_dataset) and enabled_of(client, admin_headers, TRIG, global_trigger_repo)
    assert store == {(NS, KEY): VALUE}

    # the same going back: still disabled, the value still in quarantine
    k8s_client["create_namespaced_secret_mock"].side_effect = working_create
    assert patch(client, admin_headers, enabled=False).status_code == 200
    working_read = k8s_client["read_namespaced_secret_mock"].side_effect
    k8s_client["read_namespaced_secret_mock"].side_effect = ApiException(status=403)
    assert patch(client, admin_headers, enabled=True).status_code == 400
    assert secret_row().enabled is False and not enabled_of(client, admin_headers, DS, global_dataset)
    assert store == {(Q, KEY): VALUE}
    k8s_client["read_namespaced_secret_mock"].side_effect = working_read


def test_a_secret_created_disabled_is_stored_in_quarantine(client, admin_headers, store):
    body = {"label": "off-creds", "provider": "K8S", "values": {"TOKEN": "t"}, "enabled": False}
    assert client.post(SEC, json=body, headers=admin_headers).status_code == 201
    assert (Q, "fn-secret-off-creds") in store and (NS, "fn-secret-off-creds") not in store


# ---------------------------------------------------------------- rotation

def test_a_disabled_secret_cannot_be_rotated_unless_the_request_enables_it(client, admin_headers, store):
    patch(client, admin_headers, enabled=False)
    for body in ({"values": {"TOKEN": "n"}}, {"values": {"TOKEN": "n"}, "enabled": False}):
        refused = patch(client, admin_headers, **body)
        assert refused.status_code == 409 and "enable it before rotating" in refused.json()["error"]
    assert store == {(Q, KEY): VALUE}

    assert patch(client, admin_headers, values={"TOKEN": "n"}, enabled=True).status_code == 200
    assert store == {(NS, KEY): {"TOKEN": base64.b64encode(b"n").decode()}}


def test_rotating_and_disabling_in_one_request_leaves_the_new_value_in_quarantine(client, admin_headers, store):
    assert patch(client, admin_headers, values={"TOKEN": "n"}, enabled=False).status_code == 200
    assert store == {(Q, KEY): {"TOKEN": base64.b64encode(b"n").decode()}}


# ---------------------------------------------------------------- delete

@pytest.mark.parametrize("base,fixture", KINDS)
def test_delete_is_refused_naming_the_enabled_users_and_allowed_once_they_are_disabled(
        client, admin_headers, store, request, base, fixture):
    resource = request.getfixturevalue(fixture)
    name = getattr(resource, "name", None) or resource.uri

    refused = client.delete(f"{SEC}/test-creds", headers=admin_headers)
    assert refused.status_code == 409 and name in refused.json()["error"]
    assert store == {(NS, KEY): VALUE} and secret_row().deleted_at is None

    assert client.patch(f"{base}/{resource.id}", json={"enabled": False}, headers=admin_headers).status_code == 200
    assert client.delete(f"{SEC}/test-creds", headers=admin_headers).status_code == 204
    assert store == {}


def test_delete_with_force_disables_the_users_first(
        client, admin_headers, store, global_dataset, global_trigger_repo, global_results_repo):
    assert client.delete(f"{SEC}/test-creds?force=true", headers=admin_headers).status_code == 204
    assert store == {}
    for base, resource in ((DS, global_dataset), (TRIG, global_trigger_repo), (RES, global_results_repo)):
        assert enabled_of(client, admin_headers, base, resource) is False
    assert client.get(f"{SEC}/test-creds", headers=admin_headers).status_code == 404


def test_a_failed_store_delete_with_force_rolls_back_the_disabling(
        client, admin_headers, store, k8s_client, global_dataset):
    k8s_client["delete_namespaced_secret_mock"].side_effect = ApiException(status=500)
    assert client.delete(f"{SEC}/test-creds?force=true", headers=admin_headers).status_code == 400
    assert secret_row().deleted_at is None
    assert enabled_of(client, admin_headers, DS, global_dataset) is True


def test_deleting_a_disabled_secret_deletes_the_value_from_quarantine(
        client, admin_headers, store, k8s_client):
    patch(client, admin_headers, enabled=False)
    assert store == {(Q, KEY): VALUE}
    assert client.delete(f"{SEC}/test-creds", headers=admin_headers).status_code == 204
    assert store == {}
    k8s_client["delete_namespaced_secret_mock"].assert_any_call(KEY, Q)


# ---------------------------------------------------------------- enabling a resource

@pytest.mark.parametrize("base,fixture", KINDS)
def test_enabling_on_a_disabled_secret_is_409_even_naming_its_own_secret_and_repointing_fixes_it(
        client, admin_headers, store, make_global_secret, request, base, fixture):
    resource = request.getfixturevalue(fixture)
    url = f"{base}/{resource.id}"
    patch(client, admin_headers, enabled=False)

    for body in ({"enabled": True}, {"enabled": True, "secret_label": "test-creds"}):
        refused = client.patch(url, json=body, headers=admin_headers)
        assert refused.status_code == 409 and "test-creds is disabled" in refused.json()["error"]
    assert enabled_of(client, admin_headers, base, resource) is False
    # without enabled, naming the secret in use stays fine
    assert client.patch(url, json={"secret_label": "test-creds"}, headers=admin_headers).status_code == 200

    make_global_secret(label="other-creds")
    fixed = client.patch(url, json={"enabled": True, "secret_label": "other-creds"}, headers=admin_headers)
    assert fixed.status_code == 200, fixed.json()
    assert fixed.json()["enabled"] is True and fixed.json()["secret"]["label"] == "other-creds"


@pytest.mark.parametrize("base,fixture", KINDS)
def test_enabling_on_a_deleted_secret_is_409_and_repointing_fixes_it(
        client, admin_headers, store, make_global_secret, request, base, fixture):
    resource = request.getfixturevalue(fixture)
    url = f"{base}/{resource.id}"
    assert client.delete(f"{SEC}/test-creds?force=true", headers=admin_headers).status_code == 204

    refused = client.patch(url, json={"enabled": True}, headers=admin_headers)
    assert refused.status_code == 409 and "test-creds is deleted" in refused.json()["error"]

    make_global_secret(label="other-creds")
    fixed = client.patch(url, json={"enabled": True, "secret_label": "other-creds"}, headers=admin_headers)
    assert fixed.status_code == 200, fixed.json()
    assert fixed.json()["enabled"] is True and fixed.json()["secret"]["label"] == "other-creds"


# ---------------------------------------------------------------- healthcheck

def test_the_healthcheck_of_a_disabled_secret_reports_it_unreadable_without_reading_the_store(
        client, admin_headers, store, k8s_client, mock_connection_checks, global_dataset, global_trigger_repo):
    patch(client, admin_headers, enabled=False)
    k8s_client["read_namespaced_secret_mock"].reset_mock()

    for url in (f"{SEC}/test-creds/healthcheck",):
        health = client.get(url, headers=admin_headers, json={})
        assert health.status_code == 200
        assert health.json()["enabled"] is False and health.json()["status"] == "secret_missing"
        assert "disabled" in health.json()["health_check"]["message"] and health.json()["keys"] == []
    assert not k8s_client["read_namespaced_secret_mock"].called
    assert client.get("/global/healthcheck", headers=admin_headers, json={}).status_code == 200
