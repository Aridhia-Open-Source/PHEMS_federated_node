import dagster as dg

from app.backend import BackendAPI
from app.utils import BackendAdapter, BackendSession
from app.config import BackendConfig
from app.definitions.sensors.git.base import GitAPIFactory


@dg.resource
def backend_config() -> BackendConfig:
    return BackendConfig()


@dg.resource(required_resource_keys={"backend_config"})
def backend_api(context) -> BackendAPI:
    config = context.resources.backend_config
    adapter = BackendAdapter(base_url=config.uri, username=config.user, password=config.password)
    session = BackendSession(adapter=adapter)
    return BackendAPI(session=session)


@dg.resource
def git_apis(context) -> GitAPIFactory:
    return GitAPIFactory()


RESOURCES = {
    "backend_config": backend_config,
    "backend_api": backend_api,
    "git_apis": git_apis,
}
