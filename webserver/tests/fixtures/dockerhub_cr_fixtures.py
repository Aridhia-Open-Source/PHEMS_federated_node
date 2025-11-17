from typing import Any, Generator
import pytest
import responses
from unittest.mock import Mock

from app.helpers.container_registries import DockerRegistry
from app.models.container import Container
from app.models.registry import Registry
from app.helpers.keycloak import KEYCLOAK_URL


DOCKER_CLASS = 'app.models.registry.DockerRegistry'

@pytest.fixture
def cr_name():
    return "dockerhubcr.io"

@pytest.fixture
def registry_client(mocker):
    mocker.patch(
        DOCKER_CLASS,
        return_value=Mock()
    )

@pytest.fixture
def cr_client(mocker, reg_k8s_client):
    return mocker.patch(
        'app.helpers.container_registries.DockerRegistry',
        return_value=Mock(
            login=Mock(return_value="access_token")
        )
    )

@pytest.fixture
def cr_client_404(mocker):
    mocker.patch(
        DOCKER_CLASS,
        return_value=Mock(
            login=Mock(return_value="access_token"),
            has_image_tag_or_sha=Mock(return_value=False)
        )
    )

@pytest.fixture
def dockerhub_login_request() -> Generator[responses.RequestsMock, Any, None]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_passthru(KEYCLOAK_URL)
        rsps.add(
            responses.GET,
            "https://hub.docker.com/v2/users/login/",
            json={"token": "12345asdf"},
            status=200
        )
        yield rsps

@pytest.fixture
def cr_class(client, cr_name, dockerhub_login_request):
    with dockerhub_login_request:
        return DockerRegistry(cr_name, creds={"user": "", "token": ""})

@pytest.fixture
def registry(client, mocker, reg_k8s_client, dockerhub_login_request, cr_name) -> Registry:
    with dockerhub_login_request:
        dockerhub_login_request.add(
            responses.GET,
            "https://hub.docker.com/v2/users/login/",
            json={"token": "12345asdf"},
            status=200
        )
        reg = Registry(cr_name, '', '')
        reg.add()
        return reg

@pytest.fixture
def container(client, k8s_client, registry, image_name) -> Container:
    img, tag = image_name.split(':')
    cont = Container(img, registry, tag, dashboard=True)
    cont.add()
    return cont
