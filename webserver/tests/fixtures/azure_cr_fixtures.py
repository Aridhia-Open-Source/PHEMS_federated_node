import base64
import json
import pytest
import responses
from unittest.mock import Mock

from app.helpers.keycloak import KEYCLOAK_URL
from app.helpers.container_registries import AzureRegistry
from app.models.container import Container
from app.models.registry import Registry


@pytest.fixture
def cr_name():
    return "acr.azurecr.io"

@pytest.fixture
def expected_image_names(container):
    return ["testimage", container.name]

@pytest.fixture
def expected_tags_list():
    return ["1.2.3", "dev"]

@pytest.fixture
def expected_digest_list():
    """
    ACR only returns one sha per tag
    """
    return "sha256:c1e51a68c68a448a"

@pytest.fixture
def registry_client(mocker):
    mocker.patch(
        'app.models.registry.AzureRegistry',
        return_value=Mock()
    )

@pytest.fixture
def azure_login_request(cr_name):
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add_passthru(KEYCLOAK_URL)
        rsps.add(
            responses.GET,
            f"https://{cr_name}/oauth2/token?service={cr_name}&scope=registry:catalog:*",
            json={"access_token": "12345asdf"},
            status=200
        )
        yield rsps

@pytest.fixture
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

@pytest.fixture
def cr_client(mocker, reg_k8s_client):
    return mocker.patch(
        'app.helpers.container_registries.AzureRegistry',
        return_value=Mock(
            login=Mock(return_value="access_token"),
            get_image_tags=Mock(return_value=["0.1.2", "1.0.0"])
        )
    )

@pytest.fixture
def cr_client_404(mocker):
    mocker.patch(
        'app.models.registry.AzureRegistry',
        return_value=Mock(
            login=Mock(return_value="access_token"),
            has_image_tag_or_sha=Mock(return_value=False)
        )
    )

@pytest.fixture
def cr_class(mocker, cr_name):
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"https://{cr_name}/oauth2/token?service={cr_name}&scope=registry:catalog:*",
            json={"access_token": "12345asdf"},
            status=200
        )
        return AzureRegistry(cr_name, creds={"user": "", "token": ""})

@pytest.fixture
def registry(client, reg_k8s_client, k8s_client, cr_name, azure_login_request) -> Registry:
    reg = Registry(cr_name, '', '')
    reg.add()
    return reg

@pytest.fixture
def container(client, k8s_client, registry, image_name) -> Container:
    img, tag = image_name.split(':')
    cont = Container(img, registry, tag, dashboard=True)
    cont.add()
    return cont

@pytest.fixture
def container_with_sha(client, k8s_client, registry, image_name, expected_digest_list) -> Container:
    img, _ = image_name.split(':')
    cont = Container(img, registry, sha=expected_digest_list, dashboard=True)
    cont.add()
    return cont
