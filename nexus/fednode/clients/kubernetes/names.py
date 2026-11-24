"""Kubernetes resource-name validators, independent of any service's error model."""
import re

DNS_LABEL = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?")
DNS_SUBDOMAIN = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*")
SECRET_KEY = re.compile(r"[-._a-zA-Z0-9]+")

DNS_LABEL_MAX = 63
DNS_SUBDOMAIN_MAX = 253
SECRET_KEY_MAX = 253


def validate_dns_label(value: str, field: str) -> str:
    """Validate a Pod name or label value."""
    if not isinstance(value, str) or len(value) > DNS_LABEL_MAX or not DNS_LABEL.fullmatch(value):
        raise ValueError(
            f"{field} must be 1 to {DNS_LABEL_MAX} lowercase alphanumerics or '-', "
            "starting and ending with an alphanumeric"
        )
    return value


def validate_dns_subdomain(value: str, field: str) -> str:
    """Validate a Secret or namespace name."""
    if not isinstance(value, str) or len(value) > DNS_SUBDOMAIN_MAX or not DNS_SUBDOMAIN.fullmatch(value):
        raise ValueError(
            f"{field} must be 1 to {DNS_SUBDOMAIN_MAX} characters of lowercase alphanumeric words "
            "separated by '.', each word using alphanumerics or '-' and starting and ending "
            "with an alphanumeric"
        )
    return value


def validate_secret_key(value: str, field: str) -> str:
    """Validate a key inside a Kubernetes Secret."""
    if not isinstance(value, str) or len(value) > SECRET_KEY_MAX or not SECRET_KEY.fullmatch(value):
        raise ValueError(f"{field} must be 1 to {SECRET_KEY_MAX} letters, digits, '-', '_' or '.'")
    return value
