from typing import Literal
import httpx
from pytest_asyncio import fixture
from unittest.mock import AsyncMock, Mock

from app.helpers.container_registries import DockerRegistry
from app.models.container import Container
from app.models.registry import Registry

from .common_registry_fixtures import *


DOCKER_CLASS = 'app.models.registry.DockerRegistry'

@fixture
def cr_name() -> Literal['dockerhubcr.io']:
    return "dockerhubcr.io"

@fixture
def registry_client(mocker):
    mocker.patch(
        DOCKER_CLASS,
        return_value=Mock()
    )

@fixture
def cr_client_404(mocker):
    mocker.patch(
        DOCKER_CLASS,
        return_value=Mock(
            login=Mock(return_value="access_token"),
            has_image_tag_or_sha=AsyncMock(return_value=False)
        )
    )

@fixture
async def dockerhub_login_request(respx_mock):
    respx_mock.get(
        "https://hub.docker.com/v2/users/login/"
    ).mock(
        return_value=httpx.Response(
            json={"token": "12345asdf"},
            status_code=200
        )
    )

@fixture
async def cr_class(client, cr_name, dockerhub_login_request) -> DockerRegistry:
    return await DockerRegistry.create(cr_name, creds={"user": "", "token": ""})

@fixture
async def registry(client, respx_mock, registry_secret_mock, dockerhub_login_request, cr_name, db_session) -> Registry:
    reg = Registry(url=cr_name, username='', password='')
    await reg.add(db_session)
    return reg

@fixture
async def container(client, k8s_client, registry, image_name, db_session) -> Container:
    img, tag = image_name.split(':')
    cont = Container(name=img, registry=registry, tag=tag, dashboard=True)
    await cont.add(db_session)
    return cont
