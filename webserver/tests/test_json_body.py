import json
import pytest
from http import HTTPStatus

from app.models.project import Project


@pytest.mark.parametrize("body", ["null", "[]", '[{"name": "x"}]', '"a string"', "42"])
class TestBodyIsNotAnObject:
    def test_post_datasets(self, client, post_json_admin_header, body):
        response = client.post("/datasets", data=body, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json["error"] == "The request body must be a JSON object"

    def test_patch_projects(self, client, project, post_json_admin_header, body):
        response = client.patch(f"/projects/{project.id}", data=body, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json["error"] == "The request body must be a JSON object"

    def test_post_tasks(self, client, post_json_admin_header, body):
        response = client.post("/tasks", data=body, headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json["error"] == "The request body must be a JSON object"


class TestJsonBodyCheck:
    def test_malformed_json(self, client, post_json_admin_header):
        response = client.post("/projects", data='{"name": ', headers=post_json_admin_header)
        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.json["error"] == "The request body must be a JSON object"

    def test_an_object_is_accepted(self, client, post_json_admin_header):
        response = client.post(
            "/projects", data=json.dumps({"name": "newproject"}), headers=post_json_admin_header
        )
        assert response.status_code == HTTPStatus.CREATED, response.json
        assert Project.query.filter_by(name="newproject").one_or_none() is not None

    def test_no_body_is_untouched(self, client, project, simple_admin_header):
        response = client.get(f"/projects/{project.id}", headers=simple_admin_header)
        assert response.status_code == HTTPStatus.OK

    def test_no_json_content_type_is_untouched(self, client, project, simple_admin_header):
        response = client.patch(f"/projects/{project.id}", data="[]", headers=simple_admin_header)
        assert response.status_code != HTTPStatus.BAD_REQUEST or "JSON object" not in response.json["error"]
