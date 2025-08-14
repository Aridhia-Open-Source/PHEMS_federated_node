import pytest

from app.helpers.exceptions import InvalidRequest
from app.models.task import Task
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *


class TestResourceValidators:
    def test_valid_values(
            self,
            mocker,
            user_uuid,
            registry_client,
            cr_client,
            mocks_kc_tasks,
            task_body
        ):
        """
        Tests that the expected resource values are accepted
        """
        task_body["resources"] = {
            "limits": {
                "cpu": "100m",
                "memory": "100Mi"
            },
            "requests": {
                "cpu": "0.1",
                "memory": "100Mi"
            }
        }
        mocker.patch("app.helpers.keycloak.Keycloak.get_token_from_headers",
                     return_value="")
        mocker.patch("app.helpers.keycloak.Keycloak.decode_token",
                     return_value={"sub": user_uuid})
        Task.validate(task_body)

    def test_invalid_memory_values(
            self,
            mocker,
            user_uuid,
            cr_client,
            registry_client,
            mocks_kc_tasks,
            task_body
        ):
        """
        Tests that the unexpected memory values are not accepted
        """
        mocker.patch("app.helpers.keycloak.Keycloak.get_token_from_headers",
                     return_value="")
        mocker.patch("app.helpers.keycloak.Keycloak.decode_token",
                     return_value={"sub": user_uuid})

        invalid_values = ["hundredMi", "100ki", "100mi", "0.1Ki", "Mi100"]
        for in_val in invalid_values:
            task_body["resources"] = {
                "limits": {
                    "cpu": "100m",
                    "memory": "100Mi"
                },
                "requests": {
                    "cpu": "0.1",
                    "memory": in_val
                }
            }
            with pytest.raises(InvalidRequest) as ir:
                Task.validate(task_body)
            assert ir.value.description == f'Memory resource value {in_val} not valid.'

    def test_invalid_cpu_values(
            self,
            mocker,
            user_uuid,
            cr_client,
            registry_client,
            mocks_kc_tasks,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        mocker.patch("app.helpers.keycloak.Keycloak.get_token_from_headers",
                     return_value="")
        mocker.patch("app.helpers.keycloak.Keycloak.decode_token",
                     return_value={"sub": user_uuid})

        invalid_values = ["5.24.1", "hundredm", "100Ki", "100mi", "0.1m"]

        for in_val in invalid_values:
            task_body["resources"] = {
                "limits": {
                    "cpu": in_val,
                    "memory": "100Mi"
                },
                "requests": {
                    "cpu": "0.1",
                    "memory": "100Mi"
                }
            }
            with pytest.raises(InvalidRequest) as ir:
                Task.validate(task_body)
            assert ir.value.description == f'Cpu resource value {in_val} not valid.'

    def test_mem_limit_lower_than_request_fails(
            self,
            mocker,
            user_uuid,
            cr_client,
            registry_client,
            mocks_kc_tasks,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        mocker.patch("app.helpers.keycloak.Keycloak.get_token_from_headers",
                     return_value="")
        mocker.patch("app.helpers.keycloak.Keycloak.decode_token",
                     return_value={"sub": user_uuid})

        task_body["resources"] = {
            "limits": {
                "cpu": "100m",
                "memory": "100Mi"
            },
            "requests": {
                "cpu": "0.1",
                "memory": "200000Ki"
            }
        }
        with pytest.raises(InvalidRequest) as ir:
            Task.validate(task_body)
        assert ir.value.description == 'Memory limit cannot be lower than request'

    def test_cpu_limit_lower_than_request_fails(
            self,
            mocker,
            user_uuid,
            cr_client,
            registry_client,
            mocks_kc_tasks,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        mocker.patch("app.helpers.keycloak.Keycloak.get_token_from_headers",
                     return_value="")
        mocker.patch("app.helpers.keycloak.Keycloak.decode_token",
                     return_value={"sub": user_uuid})

        task_body["resources"] = {
            "limits": {
                "cpu": "100m",
                "memory": "100Mi"
            },
            "requests": {
                "cpu": "0.2",
                "memory": "100Mi"
            }
        }
        with pytest.raises(InvalidRequest) as ir:
            Task.validate(task_body)
        assert ir.value.description == 'Cpu limit cannot be lower than request'
