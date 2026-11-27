import pytest
from pydantic import ValidationError

from fednode.clients.nexus.models import TaskCompute

LIMITS = {"max_cpu": "4", "max_memory": "16Gi", "default_limit_cpu": "2", "default_limit_memory": "4Gi"}


class TestWithoutLimits:
    def test_an_empty_compute_is_valid_and_keeps_nothing(self):
        assert TaskCompute().model_dump(exclude_none=True) == {}

    @pytest.mark.parametrize("compute", [
        {"limits": {"cpu": "100m", "memory": "100Mi"}, "requests": {"cpu": "0.1", "memory": "100Mi"}},
        {"limits": {"cpu": "1", "memory": "2e6"}, "requests": {"cpu": "0.1", "memory": "1M"}},
        # Nothing is over a node max the validation was not given
        {"limits": {"cpu": "64", "memory": "1Ei"}},
    ])
    def test_accepted(self, compute):
        assert TaskCompute.model_validate(compute).model_dump(exclude_none=True) == compute

    @pytest.mark.parametrize("compute", [
        {"limits": {"memory": "hundredMi"}},
        {"limits": {"memory": "0.1Ki"}},
        {"requests": {"cpu": "5.24.1"}},
        {"limits": {"cpu": "0.1m"}},
        {"limits": {"gpu": "1"}},
    ])
    def test_a_quantity_has_to_be_a_kubernetes_quantity(self, compute):
        with pytest.raises(ValidationError):
            TaskCompute.model_validate(compute)

    @pytest.mark.parametrize("compute, message", [
        ({"requests": {"cpu": "0.2"}, "limits": {"cpu": "100m"}}, "compute.limits.cpu 100m is lower than its request 0.2"),
        (
            {"requests": {"memory": "200000Ki"}, "limits": {"memory": "100Mi"}},
            "compute.limits.memory 100Mi is lower than its request 200000Ki",
        ),
    ])
    def test_a_limit_is_not_lower_than_its_request(self, compute, message):
        with pytest.raises(ValidationError, match=message):
            TaskCompute.model_validate(compute)


class TestWithLimits:
    def validate(self, compute):
        return TaskCompute.model_validate(compute, context={"limits": LIMITS})

    @pytest.mark.parametrize("compute, message", [
        ({"limits": {"cpu": "5"}}, "compute.limits.cpu 5 is over the node max 4"),
        ({"requests": {"memory": "17Gi"}}, "compute.requests.memory 17Gi is over the node max 16Gi"),
        ({"requests": {"cpu": "3"}}, "compute.requests.cpu 3 is over the default limit 2, give a compute.limits.cpu with it"),
    ])
    def test_nothing_is_over_the_node_limits(self, compute, message):
        with pytest.raises(ValidationError, match=message):
            self.validate(compute)

    def test_a_request_over_the_default_limit_is_fine_with_a_limit_of_its_own(self):
        compute = {"requests": {"cpu": "3"}, "limits": {"cpu": "4"}}

        assert self.validate(compute).model_dump(exclude_none=True) == compute
