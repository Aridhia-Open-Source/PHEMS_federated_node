import pytest

from app.helpers.exceptions import InvalidRequest
from app.dtos.task_spec import TaskSpecRequest
from tests.fixtures.tasks_fixtures import *


class TestComputeValidators:
    def test_valid_values(
            self,
            task_body
        ):
        """
        Tests that the expected resource values are accepted
        """
        task_body["compute"] = {
            "limits": {
                "cpu": "100m",
                "memory": "100Mi"
            },
            "requests": {
                "cpu": "0.1",
                "memory": "100Mi"
            }
        }
        TaskSpecRequest.from_api_body(task_body)

    def test_valid_values_exp(
            self,
            task_body
        ):
        """
        Tests that the expected resource values are accepted
        """
        task_body["compute"] = {
            "limits": {
                "cpu": "1",
                "memory": "2e6"
            },
            "requests": {
                "cpu": "0.1",
                "memory": "1M"
            }
        }
        TaskSpecRequest.from_api_body(task_body)

    def test_invalid_memory_values(
            self,
            task_body
        ):
        """
        Tests that the unexpected memory values are not accepted
        """
        invalid_values = ["hundredMi", "100ki", "100mi", "0.1Ki", "Mi100"]
        for in_val in invalid_values:
            task_body["compute"] = {
                "limits": {
                    "cpu": "100m",
                    "memory": in_val
                },
                "requests": {
                    "cpu": "0.1",
                    "memory": in_val
                }
            }
            with pytest.raises(InvalidRequest) as ir:
                TaskSpecRequest.from_api_body(task_body)
            assert 'compute.limits.memory: String should match pattern' in ir.value.description

    def test_invalid_cpu_values(
            self,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        invalid_values = ["5.24.1", "hundredm", "100Ki", "100mi", "0.1m"]

        for in_val in invalid_values:
            task_body["compute"] = {
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
                TaskSpecRequest.from_api_body(task_body)
            assert 'compute.limits.cpu: String should match pattern' in ir.value.description

    def test_mem_limit_lower_than_request_fails(
            self,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        task_body["compute"] = {
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
            TaskSpecRequest.from_api_body(task_body)
        assert 'compute.limits.memory 100Mi is lower than its request 200000Ki' in ir.value.description

    def test_cpu_limit_lower_than_request_fails(
            self,
            task_body
        ):
        """
        Tests that the unexpected cpu values are not accepted
        """
        task_body["compute"] = {
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
            TaskSpecRequest.from_api_body(task_body)
        assert 'compute.limits.cpu 100m is lower than its request 0.2' in ir.value.description
