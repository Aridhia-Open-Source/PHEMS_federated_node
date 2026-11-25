"""
A project owned by a group (ADR 0036): only members of that group may add, change or remove the project's
datasets, secrets, trigger repositories and results repository. Anyone else gets a 409 and nothing changes.
"""
import pytest

from app.database.base_model import db
from app.models.project_dataset import ProjectDataset
from app.models.project_results_repository import ProjectResultsRepository
from app.models.project_secret import ProjectSecret
from app.models.project_trigger_repository import ProjectTriggerRepository
from tests.test_users_and_ownership import GROUP, as_, callers  # noqa: F401 pylint: disable=unused-import

# kind -> (the assigned fixture, its global resource fixture, the global resource's key in the path, the
# path under the project, the project resource model, the body of a PUT)
KINDS = {
    "dataset": ("assigned_dataset", "global_dataset", "id", "datasets", ProjectDataset, {}),
    "secret": ("assigned_secret", "global_secret", "label", "secrets", ProjectSecret, {}),
    "trigger repository": (
        "assigned_trigger_repo", "global_trigger_repo", "id", "repositories/triggers", ProjectTriggerRepository,
        {"watch_dir": "triggers", "base_branch": "main"},
    ),
    "results repository": (
        "assigned_results_repo", "global_results_repo", "id", "repositories/results", ProjectResultsRepository,
        {"target_dir": "results", "base_branch": "main"},
    ),
}


def _setup(request, project, kind):
    assigned, global_fixture, key, path, model, put_body = KINDS[kind]
    request.getfixturevalue(assigned)
    resource = getattr(request.getfixturevalue(global_fixture), key)
    project.owner_group = GROUP
    db.session.commit()
    row = model.query.filter_by(project_id=project.id).one()
    return f"/projects/{project.id}/{path}/{resource}", row, put_body


def _unchanged(row):
    db.session.expire_all()
    found = db.session.query(type(row)).execution_options(include_deleted=True).filter_by(id=row.id).one()
    assert (found.deleted_at, found.enabled) == (None, True)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_a_change_to_a_project_resource_of_a_project_owned_by_another_group_is_a_409(
    request, client, project, callers, kind, method
):
    url, row, put_body = _setup(request, project, kind)
    body = {"put": {**put_body, "enabled": False}, "patch": {"enabled": False}}.get(method)

    response = client.request(method.upper(), url, json=body, headers=as_("admin_token"))

    assert response.status_code == 409, response.text
    assert GROUP in response.json()["error"]
    _unchanged(row)


@pytest.mark.parametrize("kind", KINDS)
def test_a_member_of_the_owner_group_changes_the_projects_resources(request, client, project, callers, kind):
    url, _, _ = _setup(request, project, kind)

    response = client.patch(url, json={"enabled": False}, headers=as_("service_token"))
    assert response.status_code == 200, response.text
    assert client.delete(url, headers=as_("service_token")).status_code == 204


def test_assigning_a_dataset_to_a_project_owned_by_another_group_is_a_409(
    client, project, global_dataset, callers
):
    project.owner_group = GROUP
    db.session.commit()

    response = client.put(f"/projects/{project.id}/datasets/{global_dataset.id}", json={}, headers=as_("admin_token"))

    assert response.status_code == 409, response.text
    assert ProjectDataset.query.filter_by(project_id=project.id).count() == 0
