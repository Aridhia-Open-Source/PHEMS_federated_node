from pytest_asyncio import fixture
from unittest.mock import Mock

from app.helpers.container_registries import GitHubRegistry
from app.models.container import Container
from app.models.registry import Registry


GH_CLASS = 'app.models.registry.GitHubClient'


@fixture
def cr_name():
    return "ghcr.io/somecr"

@fixture
def registry_client(mocker):
    mocker.patch(
        GH_CLASS,
        return_value=Mock()
    )

@fixture
def cr_client(mocker, reg_k8s_client):
    return mocker.patch(
        'app.helpers.container_registries.GitHubClient',
        return_value=Mock(
            login=Mock(return_value="access_token"),
        )
    )

@fixture
def cr_class(cr_name) -> GitHubRegistry:
    return GitHubRegistry(cr_name, creds={"user": "", "token": "sometoken"})

@fixture
def cr_client_404(mocker):
    mocker.patch(
        GH_CLASS,
        return_value=Mock(
            login=Mock(return_value="access_token"),
            has_image_tag_or_sha=Mock(return_value=False)
        )
    )

@fixture
async def registry(client, reg_k8s_client, cr_name, db_session) -> Registry:
    reg = Registry(url=cr_name, username='', password='')
    await reg.add(db_session)
    return reg

@fixture
async def container(client, k8s_client, registry, image_name, db_session) -> Container:
    img, tag = image_name.split(':')
    cont = Container(name=img, registry=registry, tag=tag, dashboard=True)
    await cont.add(db_session)
    return cont
