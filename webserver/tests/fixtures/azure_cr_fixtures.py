import httpx
from  pytest_asyncio import fixture
import responses
from unittest.mock import AsyncMock, Mock

from app.helpers.keycloak import KEYCLOAK_URL
from app.helpers.container_registries import AzureRegistry
from app.models.container import Container
from app.models.registry import Registry

from .common_registry_fixtures import *


@fixture
def cr_name():
    return "acr.azurecr.io"

@fixture
def expected_image_names(container):
    return ["testimage", container.name]

@fixture
def expected_tags_list():
    return ["1.2.3", "dev", "latest"]

@fixture
def expected_digest_list():
    """
    ACR only returns one sha per tag
    """
    return "sha256:c1e51a68c68a448a"

@fixture
def registry_client(mocker):
    mocker.patch(
        'app.models.registry.AzureRegistry',
        return_value=AsyncMock()
    )

@fixture
async def azure_login_request(cr_name, respx_mock):
    respx_mock.get(
        f"https://{cr_name}/oauth2/token",
        params={
            "service": cr_name,
            "scope": "registry:catalog:*"
        }
    ).mock(
        return_value=httpx.Response(
            json={"access_token": "12345asdf"},
            status_code=200
        )
    )

@fixture
def tags_request(respx_mock, azure_login_request, expected_tags_list, expected_digest_list, expected_image_names, cr_name):
    for image in expected_image_names:
        respx_mock.get(
            f"https://{cr_name}/oauth2/token",
            params={
                "service": cr_name,
                "scope": f"repository:{image}:*"
            }
        ).mock(
            return_value=httpx.Response(
                json={"access_token": "12345asdf"},
                status_code=200
            )
        )
        respx_mock.get(
            f"https://{cr_name}/v2/{image}/tags/list"
        ).mock(
            return_value=httpx.Response(
                json={"tags": expected_tags_list},
                status_code=200
            )
        )
        for t in expected_tags_list:
            respx_mock.get(
                f"https://{cr_name}/v2/{image}/manifests/{t}"
            ).mock(
                return_value=httpx.Response(
                    json={"config": {"digest": expected_digest_list}},
                    status_code=200
                )
            )
        respx_mock.get(
            f"https://{cr_name}/v2/_catalog"
        ).mock(
            return_value=httpx.Response(
                json={"repositories": expected_image_names},
                status_code=200
            )
        )

@fixture
def cr_client(mocker, registry_secret_mock):
    return mocker.patch(
        'app.helpers.container_registries.AzureRegistry',
        return_value=Mock(
            login=Mock(return_value="access_token"),
            get_image_tags=Mock(return_value=["0.1.2", "1.0.0"])
        )
    )

@fixture
def cr_client_404(mocker):
    mocker.patch(
        'app.models.registry.AzureRegistry',
        return_value=Mock(
            login=Mock(return_value="access_token"),
            has_image_tag_or_sha=AsyncMock(return_value=False)
        )
    )

@fixture
async def cr_class(respx_mock, cr_name):
    respx_mock.get(
        f"https://{cr_name}/oauth2/token",
        params={
            "service": cr_name,
            "scope": "registry:catalog:*"
        }
    ).mock(
        return_value=httpx.Response(
            json={"access_token": "12345asdf"},
            status_code=200
        )
    )
    return AzureRegistry(cr_name, creds={"user": "", "token": ""})

@fixture
async def registry(client, registry_secret_mock, k8s_client, cr_name, azure_login_request, db_session) -> Registry:
    reg = Registry(url=cr_name, username='', password='')
    await reg.add(db_session)
    return reg

@fixture
async def container(k8s_client, registry, image_name, db_session) -> Container:
    img, tag = image_name.split(':')
    cont = Container(name=img, registry=registry, tag=tag, dashboard=True)
    await cont.add(db_session)
    return cont

@fixture
async def container_with_sha(k8s_client, registry, image_name, expected_digest_list, db_session) -> Container:
    img, _ = image_name.split(':')
    cont = Container(name=img, registry=registry, sha=expected_digest_list, dashboard=True)
    await cont.add(db_session)
    return cont
