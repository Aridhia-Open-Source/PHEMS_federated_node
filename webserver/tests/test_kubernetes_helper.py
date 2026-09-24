"""
Tests for the KubernetesClient helpers that wrap k8s REST API calls.
    - create_secret
"""

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
