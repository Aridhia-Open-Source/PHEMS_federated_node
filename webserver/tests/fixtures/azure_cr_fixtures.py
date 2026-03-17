from  pytest_asyncio import fixture
import responses
from unittest.mock import Mock

from app.helpers.container_registries import AzureRegistry
from app.models.container import Container
from app.models.registry import Registry
from app.helpers.settings import kc_settings


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
        return_value=Mock()
    )

@fixture
def azure_login_request(cr_name):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_passthru(kc_settings.keycloak_url)
        rsps.add(
            responses.GET,
            f"https://{cr_name}/oauth2/token?service={cr_name}&scope=registry:catalog:*",
            json={"access_token": "12345asdf"},
            status=200
        )
        yield rsps

@fixture
def tags_request(azure_login_request, expected_tags_list, expected_digest_list, expected_image_names, cr_name):
    for image in expected_image_names:
        azure_login_request.add(
            responses.GET,
            f"https://{cr_name}/oauth2/token?service={cr_name}&scope=repository:{image}:*",
            json={"access_token": "12345asdf"},
            status=200
        )
        azure_login_request.add(
            responses.GET,
            f"https://{cr_name}/v2/{image}/tags/list",
            json={"tags": expected_tags_list},
            status=200
        )
        for t in expected_tags_list:
            azure_login_request.add(
                responses.GET,
                f"https://{cr_name}/v2/{image}/manifests/{t}",
                json={"config": {"digest": expected_digest_list}},
                status=200
            )
    azure_login_request.add(
        responses.GET,
        f"https://{cr_name}/v2/_catalog",
        json={"repositories": expected_image_names},
        status=200
    )
    yield azure_login_request

@fixture
def cr_client(mocker, reg_k8s_client):
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
            has_image_tag_or_sha=Mock(return_value=False)
        )
    )

@fixture
def cr_class(mocker, cr_name):
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"https://{cr_name}/oauth2/token?service={cr_name}&scope=registry:catalog:*",
            json={"access_token": "12345asdf"},
            status=200
        )
        return AzureRegistry(cr_name, creds={"user": "", "token": ""})

@fixture
async def registry(client, reg_k8s_client, k8s_client, cr_name, azure_login_request, db_session) -> Registry:
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
