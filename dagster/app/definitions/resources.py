import dagster as dg

from app.backend import BackendAPI
from app.utils import BackendAdapter, BackendSession
from app.config import BackendConfig, SensorConfig, GithubConfig
from app.github import GithubAPI, GithubClient


@dg.resource
def backend_config() -> BackendConfig:
    return BackendConfig()


@dg.resource
def sensor_config() -> SensorConfig:
    return SensorConfig()


@dg.resource
def github_config() -> GithubConfig:
    return GithubConfig()


@dg.resource(required_resource_keys={"backend_config"})
def backend_api(context) -> BackendAPI:
    config = context.resources.backend_config
    adapter = BackendAdapter(base_url=config.uri, username=config.user, password=config.password)
    session = BackendSession(adapter=adapter)
    return BackendAPI(session=session)


@dg.resource(required_resource_keys={"github_config"})
def github_api(context) -> GithubAPI:
    config = context.resources.github_config
    client = GithubClient(token=config.token, base_uri=config.base_uri)
    return GithubAPI(client)


RESOURCES = {
    "backend_config": backend_config,
    "sensor_config": sensor_config,
    "github_config": github_config,
    "backend_api": backend_api,
    "github_api": github_api,
}
