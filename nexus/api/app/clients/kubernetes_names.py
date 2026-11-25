"""
Kubernetes' naming rules, for input that ends up as the name of a Kubernetes object.
Each check raises InvalidRequest, so a bad value is a 400 instead of a failed cluster call.
"""
import re

from app.helpers.exceptions import InvalidRequest

DNS_LABEL = re.compile(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?')
DNS_SUBDOMAIN = re.compile(r'[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*')
SECRET_KEY = re.compile(r'[-._a-zA-Z0-9]+')

DNS_LABEL_MAX = 63
DNS_SUBDOMAIN_MAX = 253
SECRET_KEY_MAX = 253


def validate_dns_label(value: str, field: str) -> str:
    """Pod names and label values: up to 63 lowercase alphanumerics or '-', starting and ending with an alphanumeric."""
    if not isinstance(value, str) or len(value) > DNS_LABEL_MAX or not DNS_LABEL.fullmatch(value):
        raise InvalidRequest(
            f"{field} must be 1 to {DNS_LABEL_MAX} lowercase alphanumerics or '-', "
            "starting and ending with an alphanumeric"
        )
    return value


def validate_dns_subdomain(value: str, field: str) -> str:
    """Secret and namespace names: dot separated DNS labels, up to 253 characters in all."""
    if not isinstance(value, str) or len(value) > DNS_SUBDOMAIN_MAX or not DNS_SUBDOMAIN.fullmatch(value):
        raise InvalidRequest(
            f"{field} must be 1 to {DNS_SUBDOMAIN_MAX} characters of lowercase alphanumeric words "
            "separated by '.', each word using alphanumerics or '-' and starting and ending "
            "with an alphanumeric"
        )
    return value


def validate_secret_key(value: str, field: str) -> str:
    """The keys inside a Secret's data."""
    if not isinstance(value, str) or len(value) > SECRET_KEY_MAX or not SECRET_KEY.fullmatch(value):
        raise InvalidRequest(
            f"{field} must be 1 to {SECRET_KEY_MAX} letters, digits, '-', '_' or '.'"
        )
    return value
