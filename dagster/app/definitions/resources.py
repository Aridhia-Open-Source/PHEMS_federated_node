import dagster as dg

from app.backend import BackendAPI
from app.utils import BackendSession, PasswordFileAdapter
from app.config import BackendConfig, settings
from app.definitions.sensors.git.base import GitAPIFactory


@dg.resource
def backend_config() -> BackendConfig:
    return settings.backend


@dg.resource(required_resource_keys={"backend_config"})
def backend_api(context) -> BackendAPI:
    config = context.resources.backend_config
    adapter = PasswordFileAdapter(base_url=config.uri, username=config.user, password_file=config.password_file)
    session = BackendSession(adapter=adapter)
    return BackendAPI(session=session)


@dg.resource(required_resource_keys={"backend_api"})
def git_apis(context) -> GitAPIFactory:
    return GitAPIFactory(context.resources.backend_api)


RESOURCES = {
    "backend_config": backend_config,
    "backend_api": backend_api,
    "git_apis": git_apis,
}
