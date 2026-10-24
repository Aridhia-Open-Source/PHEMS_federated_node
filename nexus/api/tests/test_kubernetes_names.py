import pytest

from app.helpers.exceptions import InvalidRequest
from app.helpers.kubernetes_names import (
    validate_dns_label, validate_dns_subdomain, validate_secret_key
)


class TestDnsLabel:
    @pytest.mark.parametrize("value", ["a", "0", "a-b", "a1-2b", "a" * 63])
    def test_valid(self, value):
        assert validate_dns_label(value, "name") == value

    @pytest.mark.parametrize("value", [
        "", "-a", "a-", "A", "a_b", "a.b", "a b", "a" * 64, None, 5,
    ])
    def test_invalid(self, value):
        with pytest.raises(InvalidRequest, match="name must be"):
            validate_dns_label(value, "name")


class TestDnsSubdomain:
    @pytest.mark.parametrize("value", [
        "a", "a.b", "a-b.c-d", "1-a.2-b", "a" * 63, "a" * 63 + "." + "b" * 63,
    ])
    def test_valid(self, value):
        assert validate_dns_subdomain(value, "name") == value

    @pytest.mark.parametrize("value", [
        "", ".", "a.", ".a", "a..b", "a.-b", "a-.b", "-a", "a-", "A", "a_b", "a b",
        "a" * 254, "a" * 252 + ".", None, 5,
    ])
    def test_invalid(self, value):
        with pytest.raises(InvalidRequest, match="name must be"):
            validate_dns_subdomain(value, "name")

    def test_length_boundary(self):
        at_limit = ".".join(["a" * 62] * 4) + ".a"
        assert len(at_limit) == 253
        validate_dns_subdomain(at_limit, "name")
        with pytest.raises(InvalidRequest):
            validate_dns_subdomain(at_limit + "a", "name")


class TestSecretKey:
    @pytest.mark.parametrize("value", ["a", "A", "0", "-", "_", ".", "a..b", ".dockerconfigjson", "A-b_c.1", "a" * 253])
    def test_valid(self, value):
        assert validate_secret_key(value, "key") == value

    @pytest.mark.parametrize("value", ["", "a b", "a/b", "a=b", "a:b", "é", "a" * 254, None, 5])
    def test_invalid(self, value):
        with pytest.raises(InvalidRequest, match="key must be"):
            validate_secret_key(value, "key")
