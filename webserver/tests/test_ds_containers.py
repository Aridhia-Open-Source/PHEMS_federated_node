from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.dataset_container_fixtures import *


class TestGetDatasetContainers:
    def test_list_all(
            self,
            client,
            ds_star_link,
            simple_admin_header
    ):
        """
        Basic test for listing all mappings for a dataset with all (*) images
        rather than explicit images
        """
        resp = client.get(
            f"/datasets/{ds_star_link.dataset_id}/containers",
            headers=simple_admin_header
        )
        assert resp.status_code == 200
        assert resp.json == ["*"]

    def test_list_images_non_star(
            self,
            client,
            ds_cont_link,
            simple_admin_header
    ):
        """
        Basic test for listing all mappings for a dataset with explicit
        images rather than all (*)
        """
        resp = client.get(
            f"/datasets/{ds_cont_link.dataset_id}/containers",
            headers=simple_admin_header
        )
        assert resp.status_code == 200
        assert resp.json == [ds_cont_link.container.sanitized_dict()]

    def test_list_images_404_dataset(
            self,
            client,
            simple_admin_header
    ):
        """
        Tests a 404 is returned if a dataset id is not found
        """
        resp = client.get(
            f"/datasets/10000/containers",
            headers=simple_admin_header
        )
        assert resp.status_code == 404
        assert resp.json["error"] == "Dataset 10000 does not exist"


class TestPostDatasetContainers:
    def test_basic_association_by_id(
            self,
            client,
            registry,
            container,
            dataset,
            post_json_admin_header
    ):
        """
        Basic test for POSTing a new association using the
        ids field
        """
        resp = client.post(
            f"/datasets/{dataset.id}/containers",
            json={
                "ids": [container.id]
            },
            headers=post_json_admin_header
        )

        assert resp.status_code == 201
        assert DatasetContainer.query.filter_by(
            dataset=dataset,
            container=container,
            use=True
        ).one_or_none() is not None

    def test_basic_association_duplicate(
            self,
            client,
            ds_cont_link,
            post_json_admin_header
    ):
        """
        Basic test for POSTing a new association using the
        ids field
        """
        resp = client.post(
            f"/datasets/{ds_cont_link.dataset.id}/containers",
            json={
                "ids": [ds_cont_link.container.id]
            },
            headers=post_json_admin_header
        )

        assert resp.status_code == 201

    def test_basic_association_by_names(
            self,
            client,
            registry,
            container,
            dataset,
            post_json_admin_header
    ):
        """
        Basic test for POSTing a new association using the
        images field
        """
        resp = client.post(
            f"/datasets/{dataset.id}/containers",
            json={
                "images": [container.full_image_name()]
            },
            headers=post_json_admin_header
        )

        assert resp.status_code == 201, resp.json
        assert DatasetContainer.query.filter_by(
            dataset=dataset,
            container=container,
            use=True
        ).one_or_none() is not None

    def test_basic_association_by_id_and_names(
            self,
            client,
            registry,
            container,
            container2,
            dataset,
            post_json_admin_header
    ):
        """
        Basic test for POSTing a new association using both the
        images and ids fields
        """
        resp = client.post(
            f"/datasets/{dataset.id}/containers",
            json={
                "images": [container.full_image_name()],
                "ids": [container2.id]
            },
            headers=post_json_admin_header
        )

        assert resp.status_code == 201, resp.json
        assert DatasetContainer.query.filter_by(
            dataset=dataset,
            container=container,
            use=True
        ).one_or_none() is not None
        assert DatasetContainer.query.filter_by(
            dataset=dataset,
            container=container2,
            use=True
        ).one_or_none() is not None

    def test_basic_association_all(
            self,
            client,
            dataset,
            post_json_admin_header
    ):
        """
        Basic test for POSTing a new association
        """
        resp = client.post(
            f"/datasets/{dataset.id}/containers",
            json={
                "ids": ['*']
            },
            headers=post_json_admin_header
        )

        assert resp.status_code == 201
        assert DatasetContainer.query.filter_by(
            dataset=dataset,
            all_containers=True
        ).one_or_none() is not None

    def test_basic_association_invalid_field(
            self,
            client,
            dataset,
            post_json_admin_header
    ):
        """
        Basic test for POSTing a new association fails
        when the expected fields are missing
        """
        resp = client.post(
            f"/datasets/{dataset.id}/containers",
            json={
                "id": ['*']
            },
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        assert resp.json["error"] == "The request body should only include `ids` or `images` as unique field"

    def test_basic_association_invalid_container_id(
            self,
            client,
            dataset,
            post_json_admin_header
    ):
        """
        Basic test for POSTing a new association fails
        when container id doesn't exist
        """
        resp = client.post(
            f"/datasets/{dataset.id}/containers",
            json={
                "ids": [5000]
            },
            headers=post_json_admin_header
        )

        assert resp.status_code == 404
        assert resp.json["error"] == "Container 5000 not found"

    def test_basic_association_invalid_container_name(
            self,
            client,
            dataset,
            post_json_admin_header,
            image_name
    ):
        """
        Basic test for POSTing a new association fails
        when container name hasn't the proper format
        """
        resp = client.post(
            f"/datasets/{dataset.id}/containers",
            json={
                "images": [image_name]
            },
            headers=post_json_admin_header
        )

        assert resp.status_code == 400
        assert resp.json["error"] == f"Image name {image_name} doesn't have the proper format. Ensure it has <registry>/<container>:<tag>"
