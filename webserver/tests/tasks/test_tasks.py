import json
import pytest
from unittest import mock

from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *


class TestNotImplementedRoutes:
    @pytest.mark.parametrize(
        "method,path,with_body",
        [
            ("get", "/tasks/", False),
            ("get", "/tasks/1", False),
            ("post", "/tasks/1/cancel", False),
            ("post", "/tasks/", True),
            ("get", "/tasks/1/results", False),
            ("get", "/tasks/1/logs", False),
            ("post", "/tasks/1/results/approve", False),
            ("post", "/tasks/1/results/block", False),
        ]
    )
    def test_route_not_implemented(
            self,
            method,
            path,
            with_body,
            request,
            client,
            simple_admin_header,
            post_json_admin_header
        ):
        """
        Tests that the task routes without an implementation return 501.
        Task creation is sent a valid body so the 501 is not a validation error.
        """
        kwargs = {"headers": simple_admin_header}
        if with_body:
            kwargs = {
                "headers": post_json_admin_header,
                "json": request.getfixturevalue("task_body")
            }
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 501
        assert response.json["error"] == "Not implemented"

    def test_get_list_tasks_base_user(
            self,
            client,
            simple_user_header,
            mock_kc_client
        ):
        """
        Tests that non-admin users cannot see the list of tasks
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False

        response = client.get(
            '/tasks/',
            headers=simple_user_header
        )
        assert response.status_code == 403


class TestValidateTask:
    def test_validate_task(
            self,
            client,
            task_body,
            cr_client,
            registry_client,
            post_json_admin_header,

        ):
        """
        Test the validation endpoint can be used by admins returns 200
        """
        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 200
        assert response.text == "Ok"

    def test_validate_task_no_tag_fails(
            self,
            post_json_admin_header,
            client,
            task_body,
            container
        ):
        """
        Tests validation returns an error when the image does not have a tag or sha
        """
        tagless_image = "".join(container.full_image_name().split(':')[:-1])
        task_body["executors"][0]["image"] = tagless_image
        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == f"{tagless_image} does not have a tag or is malformed. Please provide one in the format <registry>/<image>:<tag> or <registry>/<image>@sha256.."

    def test_validate_task_no_name_fails(
            self,
            post_json_admin_header,
            client,
            task_body,

        ):
        """
        Tests validation returns an error when name is empty or null
        """
        for value in ["", None]:
            task_body["name"] = value
            response = client.post(
                '/tasks/validate',
                json=task_body,
                headers=post_json_admin_header
            )
            assert response.status_code == 400
            assert response.json["error"] == "name is a mandatory field"

    def test_validate_task_space_name_fails(
            self,
            post_json_admin_header,
            client,
            task_body,

        ):
        """
        Tests validation returns an error when name is one or more spaces
        """
        for value in [" ", " " * 10]:
            task_body["name"] = value
            response = client.post(
                '/tasks/validate',
                json=task_body,
                headers=post_json_admin_header
            )
            assert response.status_code == 400
            assert response.json["error"] == "name is a mandatory field"

    def test_validate_task_with_ds_name(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            dataset,
            task_body,

        ):
        """
        Tests validation with a dataset name returns 200
        """
        data = task_body
        data["tags"].pop("dataset_id")
        data["tags"]["dataset_name"] = dataset.name

        response = client.post(
            '/tasks/validate',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 200

    def test_validate_task_with_ds_name_and_id(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            dataset,
            task_body,

        ):
        """
        Tests validation with a dataset name and id returns 200
        """
        data = task_body
        data["tags"]["dataset_name"] = dataset.name

        response = client.post(
            '/tasks/validate',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 200

    def test_validate_task_with_conflicting_ds_name_and_id(
            self,
            cr_client,
            post_json_admin_header,
            client,
            dataset,
            task_body,

        ):
        """
        Tests validation with a dataset name that does not exists
        and a valid id returns 404
        """
        data = task_body
        data["tags"]["dataset_name"] = "something else"

        response = client.post(
            '/tasks/validate',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json["error"] == f"Dataset \"something else\" with id {dataset.id} does not exist"

    def test_validate_task_with_non_existing_dataset(
            self,
            cr_client,
            post_json_admin_header,
            client,
            task_body,

        ):
        """
        Tests validation returns 404 when the requested dataset doesn't exist
        """
        data = task_body
        data["tags"]["dataset_id"] = 123456

        response = client.post(
            '/tasks/validate',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json == {"error": "Dataset 123456 does not exist"}

    def test_validate_task_with_non_existing_dataset_name(
            self,
            cr_client,
            post_json_admin_header,
            client,
            dataset,
            task_body,

        ):
        """
        Tests validation returns 404 when the
        requested dataset name doesn't exist
        """
        data = task_body
        data["tags"].pop("dataset_id")
        data["tags"]["dataset_name"] = "something else"

        response = client.post(
            '/tasks/validate',
            data=json.dumps(data),
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json == {"error": "Dataset something else does not exist"}

    @mock.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=False)
    def test_validate_unauthorized_task(
            self,
            kc_valid_mock,
            cr_client,
            post_json_user_header,
            dataset,
            client,
            task_body,
            mock_kc_client
        ):
        """
        Tests validation returns 403 if a user is not authorized to
        access the dataset
        """
        data = task_body
        data["dataset_id"] = dataset.id

        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False

        response = client.post(
            '/tasks/validate',
            data=json.dumps(data),
            headers=post_json_user_header
        )
        assert response.status_code == 403

    def test_validate_task_image_with_digest(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            container_with_sha,
            task_body
        ):
        """
        Tests validation returns 200 with the image sha rather than
        an image tag
        """
        task_body["executors"][0]["image"] = container_with_sha.full_image_name()
        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 200

    def test_validate_task_image_same_name_different_registry(
            self,
            cr_client,
            registry_client,
            post_json_admin_header,
            client,
            container,
            task_body,
            project,
        ):
        """
        Tests validation is successful if two images are mapped with the
        same name, but different registry
        """
        registry = Registry(url="another.azurecr.io", username="user", password="pass")
        registry.add()
        WhitelistedImage(registry=registry, name=container.name, tag=container.tag, project_id=project.id).add()
        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 200

    def test_validate_task_image_not_found(
            self,
            cr_client_404,
            post_json_admin_header,
            client,
            task_body,

        ):
        """
        Tests validation returns 404 with a requested docker image is not found
        """
        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 404
        assert response.json == {"error": f"Image {task_body["executors"][0]["image"]} not found on our repository"}

    def test_validate_task_image_not_whitelisted(
            self,
            mocker,
            post_json_admin_header,
            client,
            task_body,
        ):
        """
        Tests validation returns 403 when image is not whitelisted and ENABLE_IMAGE_WHITELIST is True
        """
        mocker.patch("app.models.task.ENABLE_IMAGE_WHITELIST", True)
        mocker.patch("app.models.whitelisted_image.WhitelistedImage.validate_image_whitelisted", return_value=False)

        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 403
        assert "is not whitelisted" in response.json["error"]

    def test_validate_task_image_whitelisted_success(
            self,
            mocker,
            post_json_admin_header,
            client,
            task_body,
        ):
        """
        Tests validation success when image is whitelisted and ENABLE_IMAGE_WHITELIST is True
        """
        mocker.patch("app.models.task.ENABLE_IMAGE_WHITELIST", True)
        mocker.patch("app.models.whitelisted_image.WhitelistedImage.validate_image_whitelisted", return_value=True)
        mocker.patch("app.models.registry.Registry.validate_image_exist", return_value=True)

        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 200

    def test_validate_task_dataset_with_repo(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            task_body,
            dataset_with_repo
        ):
        """
        Simple test to make sure the task validates with a specific dataset repo
        """
        task_body["tags"] = {}
        task_body["repository"] = "organisation/repository"
        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 200

    def test_validate_task_dataset_with_repo_unlinked(
            self,
            cr_client,
            post_json_admin_header,
            client,
            registry_client,
            task_body,
            dataset_with_repo
        ):
        """
        Simple test to make sure the task is not valid if the repository provided
        has no dataset linked to it
        """
        task_body["tags"] = {}
        task_body["repository"] = "organisation/repository2"
        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == "No datasets linked with the repository organisation/repository2"

    def test_validate_task_admin_missing_dataset(
            self,
            client,
            task_body,
            cr_client,
            registry_client,
            post_json_admin_header,
            dataset,
            project,
        ):
        """
        A task naming only a project runs against that project's default dataset, so an
        admin no longer has to name one.
        """
        task_body["tags"].pop("dataset_id")
        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 200, response.json
        assert project.default_dataset_id == dataset.id

    def test_validate_task_project_without_default_dataset(
            self,
            client,
            task_body,
            cr_client,
            registry_client,
            post_json_admin_header,
            other_project,
        ):
        """
        A project with no datasets has no default, so the dataset has to be named.
        """
        task_body["tags"].pop("dataset_id")
        task_body["project_id"] = other_project.id
        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "has no default dataset" in response.json["error"]

    def test_validate_task_dataset_from_another_project(
            self,
            client,
            task_body,
            cr_client,
            registry_client,
            post_json_admin_header,
            other_project,
        ):
        """
        Naming a project and a dataset that belong to different projects is a conflict,
        not something to silently resolve one way or the other.
        """
        task_body["project_id"] = other_project.id
        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert "does not belong to project" in response.json["error"]

    def test_validate_task_basic_user(
            self,
            client,
            task_body,
            cr_client,
            registry_client,
            post_json_user_header: dict[str, str],
            access_request,
            user_uuid,
            mock_kc_client
        ):
        """
        Test the validation endpoint can be used by non-admins returns 200
        """
        mock_kc_client["wrappers_kc"].return_value.get_user_by_username.return_value = {"id": user_uuid}

        post_json_user_header["project-name"] = access_request.project_name
        response = client.post(
            '/tasks/validate',
            json=task_body,
            headers=post_json_user_header
        )
        assert response.status_code == 200, response.json
