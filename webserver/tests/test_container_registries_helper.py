import responses

def test_cr_login_failed(
       cr_class,
       cr_name
):
    """
    Test that the ContainerRegistryClient behaves as expected when the login fails.
    """
    image = 'testimage'
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"https://{cr_name}/oauth2/token?service={cr_name}&scope=repository:{image}:metadata_read",
            status=401
        )
        assert not cr_class.login(cr_name, "", image)

def test_cr_metadata_empty(
        cr_class,
        cr_name
):
    """
    Test that the ContainerRegistryClient behaves as expected when the
        metadata response is empty. Which is a `False`
    """
    image = 'testimage:1.2'
    image_name = image.split(':')[0]
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"https://{cr_name}/oauth2/token?service={cr_name}&scope=repository:{image_name}:metadata_read",
            json={"access_token": "12345asdf"},
            status=200
        )
        rsps.add(
            responses.GET,
            f"https://{cr_name}/v2/{image_name}/tags/list",
            json=[],
            status=200
        )
        assert not cr_class.find_image_repo(image)

def test_cr_metadata_tag_not_in_api_response(
        cr_class,
        cr_name
):
    """
    Test that the ContainerRegistryClient behaves as expected when the
        tag is not in the list of the metadata info. Which is a `False`
    """
    image = 'testimage:1.2'
    image_name = image.split(':')[0]
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            f"https://{cr_name}/oauth2/token?service={cr_name}&scope=repository:{image_name}:metadata_read",
            json={"access_token": "12345asdf"},
            status=200
        )
        rsps.add(
            responses.GET,
            f"https://{cr_name}/v2/{image_name}/tags/list",
            json={"tags": ["latest", "1.0"]},
            status=200
        )
        assert not cr_class.find_image_repo(image)
