import pytest
from unittest.mock import Mock

from app.helpers.container_registries import GitHubRegistry
from app.models.container import Container
from app.models.registry import Registry


GH_CLASS = 'app.models.registry.GitHubClient'


@pytest.fixture
def cr_name():
    return "ghcr.io/somecr"

@pytest.fixture
def registry_client(mocker):
    mocker.patch(
        GH_CLASS,
        return_value=Mock()
    )

@pytest.fixture
def cr_client(mocker):
    return mocker.patch(
        'app.helpers.container_registries.GitHubClient',
        return_value=Mock(
            login=Mock(return_value="access_token"),
            get_image_tags=Mock(return_value=True)
        )
    )

@pytest.fixture
def cr_class(mocker, cr_name, ):
    return GitHubRegistry(cr_name, creds={"user": "", "token": "sometoken"})

@pytest.fixture
def cr_client_404(mocker):
    mocker.patch(
        GH_CLASS,
        return_value=Mock(
            login=Mock(return_value="access_token"),
            get_image_tags=Mock(return_value=False)
        )
    )

@pytest.fixture
def registry(client, k8s_client, cr_name) -> Registry:
    reg = Registry(cr_name, '', '')
    reg.add()
    return reg

@pytest.fixture
def container(client, k8s_client, registry, image_name) -> Container:
    img, tag = image_name.split(':')
    cont = Container(img, registry, tag, True)
    cont.add()
    return cont
