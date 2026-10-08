import dagster as dg

from app.backend import BackendAPI
from app.utils import BackendAdapter, BackendSession
from app.config import BackendConfig, SensorConfig, GithubConfig, GiteaConfig, KubernetesConfig
from app.definitions.sensors.git.base import GitAPIFactory
from app.gitea import GiteaAPI, GiteaClient
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


@dg.resource
def kubernetes_config() -> KubernetesConfig:
    return KubernetesConfig()


@dg.resource(required_resource_keys={"backend_config"})
def backend_api(context) -> BackendAPI:
    config = context.resources.backend_config
    adapter = BackendAdapter(base_url=config.uri, username=config.user, password=config.password)
    session = BackendSession(adapter=adapter)
    return BackendAPI(session=session)


@dg.resource
def gitea_config() -> GiteaConfig:
    return GiteaConfig()


@dg.resource(required_resource_keys={"gitea_config"})
def gitea_api(context) -> GiteaAPI:
    config = context.resources.gitea_config
    client = GiteaClient(token=config.token, base_uri=config.base_uri)
    return GiteaAPI(client)


@dg.resource(required_resource_keys={"github_config"})
def github_api(context) -> GithubAPI:
    config = context.resources.github_config
    client = GithubClient(token=config.token, base_uri=config.base_uri)
    return GithubAPI(client)


@dg.resource
def git_apis(context) -> GitAPIFactory:
    return GitAPIFactory()


RESOURCES = {
    "backend_config": backend_config,
    "sensor_config": sensor_config,
    "gitea_config": gitea_config,
    "gitea_api": gitea_api,
    "github_config": github_config,
    "kubernetes_config": kubernetes_config,
    "backend_api": backend_api,
    "github_api": github_api,
    "git_apis": git_apis,
}
