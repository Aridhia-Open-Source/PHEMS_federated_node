"""
Git provider health: does its API answer, without a token.
"""
from collections.abc import Callable

from app.dtos.healthcheck import GitProviderHealthDTO
from app.health.run import health_check_dto
from app.models.git_provider import GitProvider


def prepare_provider_health(provider: GitProvider) -> Callable[[], GitProviderHealthDTO]:
    """A global git provider: does its API answer, without a token."""
    id, name, type, uri, api_uri, enabled = (
        provider.id, provider.name, provider.type, provider.uri, provider.api_uri, provider.enabled
    )
    prepared = provider.prepare_connection_check()

    def run():
        check = prepared()
        return GitProviderHealthDTO(
            id=id, name=name, type=type, uri=uri, api_uri=api_uri, enabled=enabled,
            status=check.status.value, health_check=health_check_dto(check),
        )
    return run
