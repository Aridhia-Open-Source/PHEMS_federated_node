from http import HTTPStatus

from app.models.project import Project


class TestGetProjects:
    def test_list_projects(self, client, project, simple_admin_header):
        response = client.get("/projects", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert any(item["id"] == project.id for item in response.json["items"])

    def test_get_project_by_id(self, client, project, simple_admin_header):
        response = client.get(f"/projects/{project.id}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK
        assert response.json["name"] == project.name

    def test_get_project_not_found(self, client, project, simple_admin_header):
        response = client.get(f"/projects/{project.id + 100}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_requires_auth(self, client, project, simple_user_header, mock_kc_client):
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False
        response = client.get("/projects", headers=simple_user_header)
        assert response.status_code == HTTPStatus.FORBIDDEN


class TestPostProject:
    def test_create_project(self, client, post_json_admin_header):
        response = client.post(
            "/projects", json={"name": "newproject"}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CREATED, response.json
        assert Project.query.filter_by(name="newproject").one_or_none() is not None

    def test_create_project_with_description(self, client, post_json_admin_header):
        response = client.post(
            "/projects",
            json={"name": "described", "description": "what it is for"},
            headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CREATED
        assert Project.query.filter_by(name="described").one().description == "what it is for"

    def test_create_duplicate_name_fails(self, client, project, post_json_admin_header):
        response = client.post(
            "/projects", json={"name": project.name}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CONFLICT

    def test_create_without_name_fails(self, client, post_json_admin_header):
        response = client.post("/projects", json={}, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_new_project_has_no_default_dataset(self, client, post_json_admin_header):
        """
        A project starts with no default. The first dataset created in it becomes one.
        """
        response = client.post(
            "/projects", json={"name": "empty"}, headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CREATED
        assert Project.query.filter_by(name="empty").one().default_dataset_id is None


class TestProjectDefaultDataset:
    """
    The seed creates a project, creates a dataset in it, and on a re-run deletes the
    dataset and creates another. The default has to survive that.
    """

    def test_first_dataset_becomes_the_default(self, client, project, dataset):
        assert project.default_dataset_id == dataset.id

    def test_second_dataset_does_not_displace_it(
            self, client, project, dataset, user_uuid, k8s_client, mock_kc_client
        ):
        from app.models.dataset import Dataset
        second = Dataset(
            name="SecondDs", host="example.com", password='pass', username='user',
            project_id=project.id
        )
        second.add(user_id=user_uuid)
        assert project.default_dataset_id == dataset.id

    def test_deleting_the_default_clears_it(self, client, project, dataset):
        """
        SET NULL rather than blocking, so re-seeding can drop the dataset and add another.
        """
        dataset.delete()
        assert project.default_dataset_id is None

    def test_reseeding_sets_a_new_default(
            self, client, project, dataset, user_uuid, k8s_client, mock_kc_client
        ):
        from app.models.dataset import Dataset
        dataset.delete()
        replacement = Dataset(
            name="Reseeded", host="example.com", password='pass', username='user',
            project_id=project.id
        )
        replacement.add(user_id=user_uuid)
        assert project.default_dataset_id == replacement.id


class TestModelRegistry:
    def test_every_relationship_resolves(self, client):
        """
        Project names DeliveryTarget and WhitelistedImage by string. Nothing imports
        delivery_target for its own sake, so if create_app() stops registering it the
        mapper cannot resolve the name and every ORM query raises. The app was shipped
        broken this way once because only the test harness imported it.
        """
        from sqlalchemy.orm import configure_mappers
        configure_mappers()

    def test_project_relationships_are_queryable(self, client, project):
        assert project.delivery_targets == []
        assert project.whitelisted_images == []
        assert project.datasets == []
