"""
Deletes that cascade to project resources follow the ownership rule of direct writes (ADR 0036): when any
project resource it would delete is owned by a group the caller is not in, the delete is a 409 naming them,
and nothing is deleted.
"""
from app.helpers.base_model import db
from app.models.project_dataset import ProjectDataset
from app.models.project_results_repository import ProjectResultsRepository
from app.models.project_secret import ProjectSecret
from app.models.project_trigger_repository import ProjectTriggerRepository
from tests.test_users_and_ownership import GROUP, as_, callers  # noqa: F401 pylint: disable=unused-import


def _owned_by_group(record):
    record.owner_group = GROUP
    db.session.commit()


def _still_there(*records):
    db.session.expire_all()
    for record in records:
        found = db.session.query(type(record)).execution_options(include_deleted=True).filter_by(id=record.id).one()
        assert found.deleted_at is None, record


def _deleted(*records):
    db.session.expire_all()
    for record in records:
        found = db.session.query(type(record)).execution_options(include_deleted=True).filter_by(id=record.id).one()
        assert found.deleted_at is not None, record


def test_a_forced_dataset_delete_is_a_409_when_a_project_resource_is_owned_by_another_group(
    client, project, global_dataset, assigned_dataset, callers
):
    resource = ProjectDataset.query.filter_by(project_id=project.id).one()
    _owned_by_group(resource)

    response = client.delete(f"/global/datasets/{global_dataset.id}?force=true", headers=as_("admin_token"))

    assert response.status_code == 409, response.json()
    assert response.json()["details"] == [{"id": project.id, "name": project.name, "owner_group": GROUP}]
    _still_there(global_dataset, resource)


def test_a_forced_dataset_delete_by_a_member_of_the_owner_group_goes_ahead(
    client, project, global_dataset, assigned_dataset, callers
):
    resource = ProjectDataset.query.filter_by(project_id=project.id).one()
    _owned_by_group(resource)

    response = client.delete(f"/global/datasets/{global_dataset.id}?force=true", headers=as_("service_token"))

    assert response.status_code == 204, response.text
    _deleted(global_dataset, resource)


def test_a_forced_results_repository_delete_is_a_409_when_a_project_resource_is_owned_by_another_group(
    client, project, global_results_repo, assigned_results_repo, callers
):
    resource = ProjectResultsRepository.query.filter_by(project_id=project.id).one()
    _owned_by_group(resource)

    response = client.delete(
        f"/global/repositories/results/{global_results_repo.id}?force=true", headers=as_("admin_token")
    )

    assert response.status_code == 409, response.json()
    assert response.json()["details"] == [{"id": project.id, "name": project.name, "owner_group": GROUP}]
    _still_there(global_results_repo, resource)


def test_a_forced_trigger_repository_delete_by_a_member_of_the_owner_group_goes_ahead(
    client, project, global_trigger_repo, assigned_trigger_repo, callers
):
    resource = ProjectTriggerRepository.query.filter_by(project_id=project.id).one()
    _owned_by_group(resource)

    response = client.delete(
        f"/global/repositories/triggers/{global_trigger_repo.id}?force=true", headers=as_("service_token")
    )

    assert response.status_code == 204, response.text
    _deleted(global_trigger_repo, resource)


def test_a_secret_delete_is_a_409_when_a_project_resource_is_owned_by_another_group(
    client, project, global_secret, assigned_secret, callers
):
    resource = ProjectSecret.query.filter_by(project_id=project.id).one()
    _owned_by_group(resource)

    response = client.delete(f"/global/secrets/{global_secret.label}", headers=as_("admin_token"))

    assert response.status_code == 409, response.json()
    assert response.json()["details"] == [{"id": project.id, "name": project.name, "owner_group": GROUP}]
    _still_there(global_secret, resource)


def test_a_project_delete_is_a_409_when_one_of_its_resources_is_owned_by_another_group(
    client, project, assigned_dataset, assigned_secret, callers
):
    owned = ProjectSecret.query.filter_by(project_id=project.id).one()
    _owned_by_group(owned)

    response = client.delete(f"/projects/{project.id}", headers=as_("admin_token"))

    assert response.status_code == 409, response.json()
    assert response.json()["details"] == [{"type": "ProjectSecret", "id": owned.id, "owner_group": GROUP}]
    _still_there(project, owned, ProjectDataset.query.filter_by(project_id=project.id).one())


def test_a_project_delete_by_a_member_of_the_owner_group_goes_ahead(
    client, project, assigned_dataset, assigned_secret, callers
):
    owned = ProjectSecret.query.filter_by(project_id=project.id).one()
    _owned_by_group(owned)
    dataset_resource = ProjectDataset.query.filter_by(project_id=project.id).one()

    response = client.delete(f"/projects/{project.id}", headers=as_("service_token"))

    assert response.status_code == 204, response.text
    _deleted(project, owned, dataset_resource)
