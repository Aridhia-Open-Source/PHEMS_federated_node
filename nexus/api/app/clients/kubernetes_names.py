"""Nexus API validation errors for shared Kubernetes resource-name rules."""
from fednode.clients.kubernetes.names import (
    validate_dns_label as _validate_dns_label,
    validate_dns_subdomain as _validate_dns_subdomain,
    validate_secret_key as _validate_secret_key,
)

from app.helpers.exceptions import InvalidRequest


def _validate(validator, value: str, field: str) -> str:
    try:
        return validator(value, field)
    except ValueError as exc:
        raise InvalidRequest(str(exc)) from exc


def validate_dns_label(value: str, field: str) -> str:
    return _validate(_validate_dns_label, value, field)


def validate_dns_subdomain(value: str, field: str) -> str:
    return _validate(_validate_dns_subdomain, value, field)


def validate_secret_key(value: str, field: str) -> str:
    return _validate(_validate_secret_key, value, field)
