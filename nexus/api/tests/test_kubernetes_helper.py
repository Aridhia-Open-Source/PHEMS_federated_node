"""
Tests for the KubernetesClient helpers that wrap k8s REST API calls.
    - create_secret
    - patch_secret_data
"""

import json

import pytest
from kubernetes.client.exceptions import ApiException
from unittest.mock import Mock

from app.helpers.exceptions import KubernetesException
from app.helpers.kubernetes import KubernetesClient


class TestKubernetesHelper:
    def test_create_secret_keeps_existing_by_default(
        self,
        k8s_client,
        k8s_config
    ):
        """
        A conflict is not an error and the existing secret is left as it is
        """
        k8s_client["create_namespaced_secret_mock"].side_effect = ApiException(
            status=409, reason="Conflict"
        )

        k8s = KubernetesClient()
        k8s.create_secret(
            name="a-secret",
            values={"PASSWORD": "newpass"},
            namespaces=["default", "tasks"]
        )

        k8s_client["patch_namespaced_secret_mock"].assert_not_called()

    def test_create_secret_overwrites_existing_when_asked(
        self,
        k8s_client,
        k8s_config
    ):
        """
        With overwrite the conflicting secret is replaced, in every namespace, with
        the values passed in - base64 encoded as the create path encodes them
        """
        k8s_client["create_namespaced_secret_mock"].side_effect = ApiException(
            status=409, reason="Conflict"
        )

        k8s = KubernetesClient()
        k8s.create_secret(
            name="a-secret",
            values={"PASSWORD": "newpass"},
            namespaces=["default", "tasks"],
            overwrite=True
        )

        patch_mock = k8s_client["patch_namespaced_secret_mock"]
        expected = {"PASSWORD": KubernetesClient.encode_secret_value("newpass")}

        assert [call.args for call in patch_mock.call_args_list] == [
            ("a-secret", "default"),
            ("a-secret", "tasks")
        ]
        for call in patch_mock.call_args_list:
            assert call.kwargs["body"].data == expected

    def test_create_secret_overwrite_failure_raises(
        self,
        k8s_client,
        k8s_config
    ):
        """
        A replace that fails is not swallowed the way the conflict is
        """
        k8s_client["create_namespaced_secret_mock"].side_effect = ApiException(
            status=409, reason="Conflict"
        )
        k8s_client["patch_namespaced_secret_mock"].side_effect = ApiException(
            http_resp=Mock(status=403, reason="Forbidden", data="Forbidden")
        )

        k8s = KubernetesClient()
        with pytest.raises(KubernetesException):
            k8s.create_secret(
                name="a-secret",
                values={"PASSWORD": "newpass"},
                namespaces=["default"],
                overwrite=True
            )

    def test_create_secret_conflict_other_status_raises(
        self,
        k8s_client,
        k8s_config
    ):
        """
        Any status other than a conflict still fails, overwrite or not
        """
        k8s_client["create_namespaced_secret_mock"].side_effect = ApiException(
            http_resp=Mock(status=500, reason="Error", data="Failed")
        )

        k8s = KubernetesClient()
        with pytest.raises(KubernetesException):
            k8s.create_secret(
                name="a-secret",
                values={"PASSWORD": "newpass"},
                namespaces=["default"],
                overwrite=True
            )
        k8s_client["patch_namespaced_secret_mock"].assert_not_called()

    def test_patch_secret_data_sends_only_the_given_keys(
        self,
        k8s_client,
        k8s_config
    ):
        """
        The body is a plain dict of the changed keys, base64 encoded: no metadata and no
        resourceVersion, so the other keys are not touched and nothing can conflict
        """
        k8s = KubernetesClient()
        k8s.patch_secret_data("a-secret", "default", {"CACHED_TOKEN_1_read": "token"})

        k8s_client["patch_namespaced_secret_mock"].assert_called_once_with(
            "a-secret", "default", body={"data": {"CACHED_TOKEN_1_read": KubernetesClient.encode_secret_value("token")}}
        )
        k8s_client["create_namespaced_secret_mock"].assert_not_called()

    def test_patch_secret_data_is_a_strategic_merge_patch_on_the_wire(
        self,
        k8s_config,
        mocker
    ):
        """
        Through the real client: a PATCH of the secret, as a strategic merge patch (a map merges its
        keys; json-patch or a replace would not), with nothing but the changed data in the body
        """
        request = mocker.patch(
            "kubernetes.client.rest.urllib3.PoolManager.request",
            return_value=Mock(status=200, reason="OK", data=b"{}"),
        )

        KubernetesClient().patch_secret_data("a-secret", "default", {"REFRESH_TOKEN": "new"})

        request.assert_called_once()
        assert request.call_args.args[0] == "PATCH"
        assert request.call_args.args[1].endswith("/api/v1/namespaces/default/secrets/a-secret")
        assert request.call_args.kwargs["headers"]["Content-Type"] == "application/strategic-merge-patch+json"
        assert json.loads(request.call_args.kwargs["body"]) == {
            "data": {"REFRESH_TOKEN": KubernetesClient.encode_secret_value("new")}
        }

    def test_patch_secret_data_failure_raises(
        self,
        k8s_client,
        k8s_config
    ):
        """
        A secret that is not there (or a patch refused) is an error, never a create
        """
        k8s_client["patch_namespaced_secret_mock"].side_effect = ApiException(
            http_resp=Mock(status=404, reason="Not Found", data="Not found")
        )

        with pytest.raises(KubernetesException):
            KubernetesClient().patch_secret_data("a-secret", "default", {"REFRESH_TOKEN": "new"})
        k8s_client["create_namespaced_secret_mock"].assert_not_called()
