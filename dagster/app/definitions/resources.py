import dagster as dg

from fednode.clients.nexus.client import BackendAPI
from fednode.http import BackendSession, PasswordFileAdapter
from app.settings import settings
from app.settings.groups import NexusSettings
from app.definitions.sensors.git.base import GitAPIFactory


@dg.resource
def backend_config() -> NexusSettings:
    return settings.services.nexus


@dg.resource(required_resource_keys={"backend_config"})
def backend_api(context) -> BackendAPI:
    config = context.resources.backend_config
    timeout = (settings.http.connect_timeout, settings.http.read_timeout)
    adapter = PasswordFileAdapter(base_url=config.uri, username=config.user, password_file=config.password_file,
                                  timeout=timeout)
    session = BackendSession(adapter=adapter)
    session.timeout = timeout
    return BackendAPI(session=session)


@dg.resource(required_resource_keys={"backend_api"})
def git_apis(context) -> GitAPIFactory:
    return GitAPIFactory(context.resources.backend_api)


RESOURCES = {
    "backend_config": backend_config,
    "backend_api": backend_api,
    "git_apis": git_apis,
}
