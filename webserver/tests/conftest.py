import base64
import json
from copy import deepcopy
from typing import List
from pytest import fixture
import pytest
from datetime import datetime as dt, timedelta
from sqlalchemy.orm.session import close_all_sessions
from sqlalchemy import text
from unittest.mock import Mock
import time

from app import create_app
from app.helpers.base_model import db, engine
from app.models.dataset import Dataset
from app.models.extras.catalogue import Catalogue
from app.models.extras.dictionary import Dictionary
from app.models.project import Project
from app.models.project_dataset import ProjectDataset
from app.models.task import Task
from app.models.extras.dar import DAR
from app.models.git_provider import ConnectionCheck, ConnectionStatus, GitProvider
from app.models.git_repository import GitRepositoryMixin
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.trigger_repository import TriggerRepository
from app.models.secret import Secret
from app.models.secret_provider_type import SecretProviderType
from app.models.project_results_repository import ProjectResultsRepository
from app.models.results_repository import ResultsRepository
from app.models.results_backend import ResultsBackend
from app.models.api_request_trigger import ApiRequestTrigger
from app.helpers.exceptions import KeycloakError
from tests.helpers.pull_requests import pr_body


@fixture(scope='session', autouse=True)
def check_database_connection():
    """Check database connectivity before running any tests. Exit entire suite if DB unavailable."""
    max_retries = 5
    retry_delay = 1
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"DB connection attempt {attempt + 1}/{max_retries} failed, retrying...")
                time.sleep(retry_delay)
            else:
                msg = f"DATABASE UNAVAILABLE: Could not connect after {max_retries} attempts: {e}"
                print(f"\n{msg}\n")
                pytest.exit(msg, 1)


sample_repo_uri = "github.com/org/test-repo"


def provider_of(uri: str, type: str = "github", api_uri: str | None = None) -> GitProvider:
    """The git provider serving a schemeless repository uri (host/owner/repo), created on first use."""
    host = uri.split("/")[0]
    provider = GitProvider.query.filter_by(uri=f"https://{host}").one_or_none()
    if provider is None:
        default_api = "https://api.github.com" if host == "github.com" else f"https://{host}/api/v1"
        provider = GitProvider(
            name=f"{type}-{host}", type=type, uri=f"https://{host}", api_uri=api_uri or default_api
        )
        provider.add()
    return provider


def new_repo(model, uri: str, secret_id: int, type: str = "github", api_uri: str | None = None):
    """A global trigger or results repository (model) at a schemeless uri, its provider found or created."""
    repo = model(
        provider_id=provider_of(uri, type, api_uri).id, repo_path="/".join(uri.split("/")[-2:]), secret_id=secret_id
    )
    repo.add()
    return repo

sample_ds_body = {
    "name": "TestDs",
    "host": "db",
    "port": 5432,
    "secret_label": "test-creds",
    "repository": sample_repo_uri,
    "catalogue": {
        "title": "test",
        "description": "test description"
    },
    "dictionaries": [{
        "table_name": "test",
        "field_name": "column1",
        "description": "test description"
    }]
}

@fixture
def image_name():
    return "example:latest"

@fixture
def user_token():
    return "user_refresh_token"

@fixture
def app_ctx(app):
    with app.app_context():
        yield

# Users' section
@fixture
def admin_user_uuid():
    return "9f18d2b5-edbc-4b4a-aab9-3a57bf67adbb"

@fixture
def user_uuid():
    return "af3301a1-8b02-47b3-8fae-a36b16a6ca32"

@fixture
def login_admin():
    return "admin_token"

@fixture
def admin_user(admin_user_uuid):
    return {"email": "admin@admin.com", "username": "admin", "id": admin_user_uuid}

@fixture
def basic_user(user_uuid):
    return {"email": "test@basicuser.com", "username": "test@basicuser.com", "id": user_uuid}

@fixture
def project_not_found(mocker):
    return mocker.patch(
        'app.helpers.wrappers.Keycloak.exchange_global_token',
        side_effect=KeycloakError("Could not find project", 400)
    )

@fixture
def simple_admin_header(login_admin):
    return {"Authorization": f"Bearer {login_admin}"}

@fixture
def post_json_admin_header(login_admin):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {login_admin}"
    }

@fixture
def simple_user_header(user_token):
    return {"Authorization": f"Bearer {user_token}"}

@fixture
def post_json_user_header(user_token):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {user_token}"
    }

@fixture
def post_form_admin_header(login_admin):
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Bearer {login_admin}"
    }


# Flask client to perform requests
@fixture
def client():
    app = create_app()
    app.testing = True
    with app.test_client() as tclient:
        with app.app_context():
            db.create_all()
            yield tclient
            close_all_sessions()
            db.drop_all()


# K8s
@fixture
def k8s_config(mocker):
    mocker.patch('kubernetes.config.load_kube_config', return_value=Mock())
    mocker.patch('app.helpers.kubernetes.config.load_kube_config', Mock())

@fixture
def v1_mock(mocker):
    return {
        "read_namespaced_secret_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.read_namespaced_secret'
        ),
        "patch_namespaced_secret_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.patch_namespaced_secret'
        ),
        "delete_namespaced_secret_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.delete_namespaced_secret'
        ),
        "create_namespaced_secret_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.create_namespaced_secret'
        )
    }


@fixture
def k8s_client(v1_mock, k8s_config):
    all_clients = {}
    all_clients.update(v1_mock)
    all_clients["read_namespaced_secret_mock"].return_value.data = {
        "USERNAME": "YWJjMTIz",
        "PASSWORD": "YWJjMTIz",
        "USER": "YWJjMTIz",
        "TOKEN": "YWJjMTIz"
    }
    return all_clients


@fixture
def reg_k8s_client(k8s_client):
    k8s_client["read_namespaced_secret_mock"].return_value.data.update({
            ".dockerconfigjson": base64.b64encode("{\"auths\": {}}".encode()).decode()
        })
    return k8s_client


@fixture
def project(client) -> Project:
    """The project datasets, tasks and whitelisted images belong to in tests."""
    project = Project(name="TestProject")
    project.locked = False
    project.add()
    return project


@fixture
def lock_project(project) -> Project:
    """The project locked and with nothing in flight, as changing its configuration needs."""
    project.locked = True
    db.session.commit()
    return project


@fixture
def enabled_project(project) -> Project:
    """The project enabled. A new Project is disabled, and the evaluate and launch sensors
    leave out disabled projects."""
    project.enabled = True
    db.session.commit()
    return project


@fixture
def make_task(client, project):
    """Factory for a task with its own ApiRequestTrigger trigger"""
    def _make(project=project, **fields) -> Task:
        api_request = ApiRequestTrigger(project_id=project.id, user_id="user")
        api_request.add()
        task = Task(
            name="task", requested_by="user", project_id=project.id, trigger_id=api_request.id,
            spec={"image": "img:1", "dataset_id": None, "env": {}}
        )
        task.spec.dataset_id = fields.pop("dataset_id", None)
        for field, value in fields.items():
            setattr(task, field, value)
        task.add()
        return task
    return _make


@fixture
def other_project(client) -> Project:
    """A second project, for checking one project cannot reach another's rows."""
    project = Project(name="OtherProject")
    project.locked = False
    project.add()
    return project


# The secret the dataset and repository fixtures reference. sample_ds_body names it too.
@fixture
def secret(client) -> Secret:
    secret = Secret(label="test-creds", provider=SecretProviderType.K8S)
    secret.add()
    return secret


# Git provider fixtures
@fixture
def git_provider(client) -> GitProvider:
    """The github.com provider the repository fixtures are on."""
    return provider_of(sample_repo_uri)


@fixture
def make_provider(client):
    """Factory for a global git provider at https://<host>, its API on the host as provider_of builds it."""
    def _make(host: str = "github.com", type: str = "github", **fields) -> GitProvider:
        provider = provider_of(f"{host}/org/repo", type)
        for name, value in fields.items():
            setattr(provider, name, value)
        db.session.commit()
        return provider
    return _make


# Trigger repository fixtures
@fixture
def trigger_repo(client, secret) -> TriggerRepository:
    """A global trigger repository, assigned to no project."""
    return new_repo(TriggerRepository, sample_repo_uri, secret.id)


@fixture
def assign_trigger(client, project, secret):
    """Factory for a global trigger repository and its assignment to a project."""
    def _assign(uri, watch_dir="", project=project, provider="github", api_uri=None):
        provider_row = provider_of(uri, provider, api_uri)
        repo = TriggerRepository.query.filter_by(
            provider_id=provider_row.id, repo_path="/".join(uri.split("/")[-2:])
        ).one_or_none()
        if repo is None:
            repo = new_repo(TriggerRepository, uri, secret.id, provider, api_uri)
        assignment = ProjectTriggerRepository(project.id, repo.id, watch_dir=watch_dir)
        assignment.add()
        return assignment
    return _assign


@fixture
def default_repo(client, user_uuid, k8s_client, mock_kc_client, project, secret, trigger_repo) -> ProjectTriggerRepository:
    """The project's assignment of the trigger repository, watching the whole repository."""
    # The project's default dataset, which a pull request of the repository runs against
    dataset = Dataset(name="DefaultDatasetForRepo", host="example.com", port=5432, secret_id=secret.id)
    dataset.add(user_id=user_uuid)
    ProjectDataset(project.id, dataset.id).add()

    assignment = ProjectTriggerRepository(project.id, trigger_repo.id, watch_dir="")
    assignment.initial_cursor = dt(2026, 1, 1)
    assignment.add()
    return assignment


# Results repository fixtures
@fixture
def results_repo(client, secret) -> ResultsRepository:
    """A global results repository, assigned to no project."""
    return new_repo(ResultsRepository, "github.com/org/results", secret.id)


@fixture
def results_assignment(client, project, results_repo) -> ProjectResultsRepository:
    """The project's assignment of the results repository."""
    assignment = ProjectResultsRepository(project.id, results_repo.id, target_dir="results")
    assignment.add()
    return assignment


# Global resources: unlinked factories, then the same linked to `project` through the PUT routes
@fixture
def admin_headers(post_json_admin_header):
    """Admin bearer token with a JSON content type, for client.get/put/post/patch/delete."""
    return post_json_admin_header


@fixture
def make_global_secret(client):
    def _make(label="test-creds") -> Secret:
        secret = Secret(label=label, provider=SecretProviderType.K8S)
        secret.add()
        return secret
    return _make


@fixture
def make_global_dataset(client, user_uuid, k8s_client, mock_kc_client, secret):
    def _make(name="GlobalDs", secret=secret) -> Dataset:
        dataset = Dataset(name=name, host="example.com", port=5432, secret_id=secret.id)
        dataset.add(user_id=user_uuid)
        return dataset
    return _make


@fixture
def make_trigger_repo(client, secret):
    def _make(uri="github.com/org/triggers", secret=secret) -> TriggerRepository:
        return new_repo(TriggerRepository, uri, secret.id)
    return _make


@fixture
def make_results_repo(client, secret):
    def _make(uri="github.com/org/results-global", secret=secret) -> ResultsRepository:
        return new_repo(ResultsRepository, uri, secret.id)
    return _make


@fixture
def global_secret(secret) -> Secret:
    return secret


@fixture
def global_dataset(make_global_dataset) -> Dataset:
    return make_global_dataset()


@fixture
def global_trigger_repo(make_trigger_repo) -> TriggerRepository:
    return make_trigger_repo()


@fixture
def global_results_repo(make_results_repo) -> ResultsRepository:
    return make_results_repo()


@fixture
def linked_secret(client, admin_headers, project, global_secret) -> dict:
    """PUT /projects/<pid>/secrets/<label>; the link as the route returns it."""
    response = client.put(f"/projects/{project.id}/secrets/{global_secret.label}", json={}, headers=admin_headers)
    assert response.status_code == 201, response.json
    return response.json


@fixture
def linked_dataset(client, admin_headers, project, global_dataset) -> dict:
    """PUT /projects/<pid>/datasets/<dataset id>; the link as the route returns it."""
    response = client.put(f"/projects/{project.id}/datasets/{global_dataset.id}", json={}, headers=admin_headers)
    assert response.status_code == 201, response.json
    return response.json


@fixture
def linked_trigger_repo(client, admin_headers, project, global_trigger_repo) -> dict:
    """PUT /projects/<pid>/repositories/triggers/<repo id>, watching "triggers"; the link as returned."""
    response = client.put(
        f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}",
        json={"watch_dir": "triggers"}, headers=admin_headers
    )
    assert response.status_code == 201, response.json
    return response.json


@fixture
def linked_results_repo(client, admin_headers, project, global_results_repo) -> dict:
    """PUT /projects/<pid>/repositories/results/<repo id>, target_dir "results"; the link as returned.
    The route needs the project locked, so it is locked for the PUT and unlocked again."""
    project.locked = True
    db.session.commit()
    response = client.put(
        f"/projects/{project.id}/repositories/results/{global_results_repo.id}",
        json={"target_dir": "results"}, headers=admin_headers
    )
    assert response.status_code == 201, response.json
    project.locked = False
    db.session.commit()
    return response.json


# A pull request posted after a link is created has to be merged after the link's cursor (the
# link's creation time when no PR is stored yet), so the default is a fixed date in the future.
PR_MERGED_AT = "2030-01-01T10:00:00Z"
# A spec file the linked_trigger_repo link (watch_dir "triggers") matches
WATCHED_SPEC_FILE = {"path": "triggers/spec.json", "status": "added"}
SPEC_RAW = json.dumps({"spec": {"image": "img:1"}})


@fixture
def make_pr_batch():
    """
    Body for POST /global/repositories/triggers/<id>/pull_requests, one valid PR per number
    (default [1]). By default each is merged at PR_MERGED_AT into "main" and adds
    triggers/spec.json, so it matches linked_trigger_repo. **fields override every PR's
    fields, e.g. base_branch="dev" or changed_files=[...].
    """
    def _make(*numbers, **fields) -> dict:
        fields = {"merged_at": PR_MERGED_AT, "changed_files": [WATCHED_SPEC_FILE], **fields}
        return {"pull_requests": [pr_body(number, **fields) for number in (numbers or (1,))]}
    return _make


@fixture
def ingest_prs(client, admin_headers, make_pr_batch):
    """
    Factory: POST the batch of make_pr_batch(*numbers, **fields) to the global trigger
    repository repo_id, assert 201 and return the response JSON {"created", "existing"}.
    """
    def _ingest(repo_id, *numbers, **fields) -> dict:
        response = client.post(
            f"/global/repositories/triggers/{repo_id}/pull_requests",
            json=make_pr_batch(*numbers, **fields), headers=admin_headers
        )
        assert response.status_code == 201, response.json
        return response.json
    return _ingest


@fixture
def pr_trigger(project, global_trigger_repo, linked_trigger_repo, ingest_prs) -> str:
    """
    PR #1 ingested after linking global_trigger_repo to `project`, so the project has an
    UNKNOWN trigger for it. Returns the URL of that trigger:
    /projects/<project id>/repositories/triggers/<repo id>/pull_requests/1
    """
    ingest_prs(global_trigger_repo.id, 1)
    return f"/projects/{project.id}/repositories/triggers/{global_trigger_repo.id}/pull_requests/1"


@fixture
def spec_raw() -> str:
    """A valid PR spec file, the body field of POST .../pull_requests/<number>/task."""
    return SPEC_RAW


@fixture
def mock_connection_checks(mocker) -> dict:
    """
    Stops the healthchecks touching the network: every repository and dataset check returns
    OK. To fail one, set e.g.
    mocks["repository"].return_value = lambda: ConnectionCheck(ConnectionStatus.UNAUTHORIZED, "Unauthorized", 401)
    Secret checks read k8s_client's read_namespaced_secret mock (keys USERNAME, PASSWORD, USER, TOKEN).
    """
    ok = lambda: ConnectionCheck(ConnectionStatus.OK, "OK")
    return {
        "repository": mocker.patch.object(GitRepositoryMixin, "prepare_connection_check", return_value=ok),
        "dataset": mocker.patch.object(Dataset, "prepare_connection_check", return_value=ok),
    }


# Dataset Mocking
@fixture()
def dataset_post_body(default_repo, project):
    return deepcopy(sample_ds_body)


@fixture
def dataset(client, user_uuid, k8s_client, mock_kc_client, project, secret) -> Dataset:
    dataset = Dataset(name="TestDs", host="example.com", port=5432, secret_id=secret.id)
    dataset.add(user_id=user_uuid)
    ProjectDataset(project.id, dataset.id).add()
    return dataset


@fixture
def dataset_with_repo(client, user_uuid, k8s_client, mock_kc_client, project, secret) -> Dataset:
    # Create dataset first
    dataset = Dataset(name="TestDsRepo", host="example.com", port=5432, secret_id=secret.id)
    dataset.add(user_id=user_uuid)
    ProjectDataset(project.id, dataset.id).add()

    # Then the repository, assigned to the project
    repo = new_repo(TriggerRepository, "github.com/organisation/repository", secret.id)
    ProjectTriggerRepository(project.id, repo.id, watch_dir="").add()

    return dataset


@fixture
def dataset_oracle(mocker, client, user_uuid, k8s_client, project, secret)  -> Dataset:
    mocker.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=True)
    dataset = Dataset(name="AnotherDS", host="example.com", port=5432, secret_id=secret.id, type="oracle")
    dataset.add(user_id=user_uuid)
    ProjectDataset(project.id, dataset.id).add()
    return dataset


@fixture
def catalogue(dataset) -> Catalogue:
    cat = Catalogue(dataset=dataset, title="new catalogue", description="shiny fresh data")
    cat.add()
    return cat


@fixture
def dictionary(dataset) -> List[Dictionary]:
    cat1 = Dictionary(dataset=dataset, description="Patient id", table_name="patients", field_name="id", label="p_id")
    cat2 = Dictionary(dataset=dataset, description="Patient info", table_name="patients", field_name="name", label="p_name")
    cat1.add()
    cat2.add()
    return [cat1, cat2]


@fixture
def dar_user():
    return "some@test.com"


@fixture
def access_request(project, dataset, user_uuid, k8s_client):
    request = DAR(
        title="TestRequest",
        project_name="example.com",
        project_id=project.id,
        requested_by=user_uuid,
        dataset=dataset,
        proj_start=dt.now().date().strftime("%Y-%m-%d"),
        proj_end=(dt.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
    )
    request.add()
    return request


@fixture
def request_base_body(project, dataset):
    return {
        "title": "TestRequest",
        "dataset_id": dataset.id,
        "project_name": "project1",
        "project_id": project.id,
        "requested_by": { "email": "test@test.com" },
        "description": "First task ever!",
        "proj_start": dt.now().date().strftime("%Y-%m-%d"),
        "proj_end": (dt.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
    }


@fixture
def request_base_body_name(project, dataset):
    return {
        "title": "Test Task",
        "dataset_name": dataset.name,
        "project_name": "project1",
        "project_id": project.id,
        "requested_by": { "email": "test@test.com" },
        "description": "First task ever!",
        "proj_start": dt.now().date().strftime("%Y-%m-%d"),
        "proj_end": (dt.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
    }


@fixture
def approve_request(mocker):
    return mocker.patch(
        'app.models.extras.dar.DAR.approve',
        return_value={"token": "somejwttoken"}
    )


@fixture
def new_user_email():
    return "test@test.com"


@fixture
def new_user(new_user_email):
    return {"email": new_user_email, "id": "8b707136-a2d8-4b69-9ab5-ec341011a62f", "username": new_user_email}


@fixture
def mock_keycloak_class(mocker):
    return mocker.patch(
        'app.models.dataset.Keycloak',
        return_value=Mock(
            get_client_id=Mock(return_value="client_id"),
            get_token=Mock(return_value="token"),
            get_policy=Mock(return_value={"id": "policy"}),
            get_scope=Mock(return_value={"id": "scope"}),
            create_policy=Mock(return_value={"id": "policy"}),
            create_resource=Mock(return_value={"_id": "resource"}),
            create_permission=Mock(return_value={"id": "permission"}),
            is_token_valid=Mock(return_value=True)
        )
    )


@fixture(autouse=True)
def mock_kc_client(mocker, basic_user, user_uuid, mock_keycloak_class):
    decode_token_return = deepcopy(basic_user)
    create_user_return = deepcopy(basic_user)
    decode_token_return["sub"] = user_uuid
    create_user_return["password"] = "tempPassword!"
    kc_mock = {
        "main_kc": mocker.patch('app.main.Keycloak', return_value=Mock(
            get_token=Mock(return_value={"access_token": "token"}),
        )),
        "wrappers_kc": mocker.patch('app.helpers.wrappers.Keycloak', return_value=Mock(
            get_token=Mock(return_value={"access_token": "token"}),
            decode_token=Mock(return_value=decode_token_return),
            get_user_by_email=Mock(return_value=basic_user),
            get_user_by_username=Mock(return_value=basic_user),
            is_user_admin=Mock(side_effect=lambda token: token == "admin_token"),
            has_user_roles=Mock(side_effect=lambda user_id, roles: False),
            is_token_valid=Mock(side_effect=lambda token, scope, *args, **kwargs: token == "admin_token" or scope != 'can_admin_request')
        )),
        # TODO(DAR): the datasets_api Keycloak mock went with the DAR code in that module
        "users_api_kc": mocker.patch('app.users_api.Keycloak', return_value=Mock(
            get_token=Mock(return_value={"access_token": "token"}),
            get_admin_token=Mock(return_value={"access_token": "admin_token"}),
            get_user_by_email=Mock(return_value=basic_user),
            list_users=Mock(return_value=[basic_user]),
            create_user=Mock(return_value=create_user_return),
            get_user_role=Mock(return_value="Users"),
        )),
        "dataset_kc": mock_keycloak_class,
        "task_kc": mocker.patch('app.models.task.Keycloak', return_value=Mock(
            get_token=Mock(return_value={"access_token": "token"}),
            get_admin_token=Mock(return_value={"access_token": "admin_token"}),
            decode_token=Mock(return_value=decode_token_return),
            get_user_by_email=Mock(return_value=basic_user),
            get_user_by_id=Mock(return_value=basic_user),
            list_users=Mock(return_value=[basic_user]),
            create_user=Mock(return_value=create_user_return),
            get_user_role=Mock(return_value="Users"),
        )),
        "tasks_api_kc": mocker.patch('app.tasks_api.Keycloak', return_value=Mock(
            get_token=Mock(return_value={"access_token": "token"}),
            get_admin_token=Mock(return_value={"access_token": "admin_token"}),
            decode_token=Mock(return_value=decode_token_return),
            get_user_by_email=Mock(return_value=basic_user),
            get_user_by_id=Mock(return_value=basic_user),
            list_users=Mock(return_value=[basic_user]),
            create_user=Mock(return_value=create_user_return),
            get_user_role=Mock(return_value="Users"),
        ))
    }
    return kc_mock
