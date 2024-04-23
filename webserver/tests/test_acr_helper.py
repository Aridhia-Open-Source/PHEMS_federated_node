from unittest.mock import Mock
import pytest
import responses
from app.helpers.exceptions import AcrException

def test_acr_login_failed(
       acr_class,
       acr_name
):
    """
    Test that the ACRClient behaves as expected when the login fails.
        This should be an AcrException
    """
    image = 'testimage'
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"https://{acr_name}/oauth2/token?service={acr_name}&scope=repository:{image}:metadata_read",
            status=401
        )
        assert not acr_class.login(acr_name, "", image)

def test_acr_metadata_empty(
        acr_class,
        acr_name
):
    """
    Test that the ACRClient behaves as expected when the
        metadata response is empty. Which is a `False`
    """
    image = 'testimage:1.2'
    image_name = image.split(':')[0]
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"https://{acr_name}/oauth2/token?service={acr_name}&scope=repository:{image_name}:metadata_read",
            json={"access_token": "12345asdf"},
            status=200
        )
        rsps.add(
            responses.GET,
            f"https://{acr_name}/v2/{image_name}/tags/list",
            json=[],
            status=200
        )
        assert not acr_class.find_image_repo(image)

def test_acr_metadata_tag_not_in_api_response(
        acr_class,
        mocker,
        acr_name
):
    """
    Test that the ACRClient behaves as expected when the
        tag is not in the list of the metadata info. Which is a `False`
    """
    image = 'testimage:1.2'
    image_name = image.split(':')[0]
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"https://{acr_name}/oauth2/token?service={acr_name}&scope=repository:{image_name}:metadata_read",
            json={"access_token": "12345asdf"},
            status=200
        )
        rsps.add(
            responses.GET,
            f"https://{acr_name}/v2/{image_name}/tags/list",
            json={"tags": ["latest", "1.0"]},
            status=200
        )
        assert not acr_class.find_image_repo(image)
