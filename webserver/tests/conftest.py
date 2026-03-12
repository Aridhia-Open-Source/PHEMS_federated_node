import asyncio
import base64
import json
from copy import deepcopy
from typing import Any, List
from datetime import datetime as dt, timedelta
from httpx import ASGITransport, AsyncClient
from kubernetes_asyncio.client import CoreV1Api, CustomObjectsApi, V1CustomResourceDefinition, V1Job, V1Pod, V1Secret
from pytest_asyncio import fixture
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker
)
from sqlalchemy import event
from unittest.mock import AsyncMock, Mock

from app.main import app
from app.helpers.const import build_sql_uri
from app.helpers.base_model import BaseModel, get_db
from app.models.dataset import Dataset
from app.models.catalogue import Catalogue
from app.models.dictionary import Dictionary
from app.models.request import RequestModel
from app.models.task import Task
from app.helpers.exceptions import KeycloakError
from app.helpers.const import CRD_DOMAIN
from app.helpers.kubernetes import BaseClient, KubernetesClient


sample_ds_body = {
    "name": "TestDs",
    "host": "db",
    "port": 5432,
    "username": "Username",
    "password": "pass",
    "catalogue": {
        "title": "test",
        "version": "1",
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

@fixture(scope="session")
def event_loop():
    """Overrides pytest-asyncio's default function-scoped event loop."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@fixture(scope="function")
async def db_session():
    """The expectation with async_sessions is that the
    transactions be called on the connection object instead of the
    session object.
    Detailed explanation of async transactional tests
    <https://github.com/sqlalchemy/sqlalchemy/issues/5811>
    """
    db_host = build_sql_uri(with_async=True)
    engine = create_async_engine(db_host)
    connection = await engine.connect()
    trans = await connection.begin()
    await connection.run_sync(BaseModel.metadata.create_all)
    async_session = async_sessionmaker(
        bind=connection, expire_on_commit=False,
    )()
    nested = await connection.begin_nested()

    @event.listens_for(async_session.sync_session, "after_transaction_end")
    def end_savepoint(session, transaction):
        nonlocal nested

        if not nested.is_active:
            nested = connection.sync_connection.begin_nested()

    yield async_session

    await trans.rollback()
    await async_session.close()
    await connection.close()
    await engine.dispose()

# FastAPI client to perform requests
@fixture(scope="function")
async def client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

@fixture
def db_secret_mock(dataset: Dataset):
    secret_return = Mock(spec=V1Secret)
    secret_return.metadata.name = dataset.get_creds_secret_name()
    secret_return.data = {
        "PGUSER": "YWJjMTIz",
        "PGPASSWORD": "YWJjMTIz",
        "USER": "YWJjMTIz",
        "TOKEN": "YWJjMTIz"
    }
    return secret_return

@fixture
def delivery_secret_mock():
    secret_return = Mock(spec=V1Secret)
    secret_return.metadata.name = "url.delivery.com"
    secret_return.data = {"auth": ""}
    return secret_return

@fixture
def pod_listed(image_name) -> Mock:
    pod = Mock(name="default_pod", spec=V1Pod)
    pod.metadata.name = "task-running"
    pod.spec.containers = [Mock(image=f"acr.azurecr.io/{image_name}")]
    pod.status.container_statuses = [Mock(
        name="default_status",
        state=Mock(
            running=None,
            waiting=None,
            terminated=Mock(
                finished_at="1/1/2024",
                exit_code="0",
                reason="Done",
                started_at="1/1/2024",
            )
        )
    )]
    return pod

# K8s
@fixture
def mock_args_k8s(db_secret_mock, pod_listed) -> AsyncMock:
    list_secret_return = Mock()
    list_secret_return.items = [db_secret_mock]

    list_pod_return = Mock()
    list_pod_return.items = [pod_listed]

    api_client_mock = AsyncMock(name="api_client")
    api_client_mock.create_namespaced_pod = AsyncMock()
    api_client_mock.list_namespaced_pod = AsyncMock(return_value=list_pod_return)
    api_client_mock.delete_namespaced_pod = AsyncMock()
    api_client_mock.read_namespaced_pod_log = AsyncMock(return_value="Example logs\nanother line")
    api_client_mock.create_persistent_volume = AsyncMock()
    api_client_mock.create_namespaced_persistent_volume_claim = AsyncMock()
    api_client_mock.create_namespaced_secret = AsyncMock()
    api_client_mock.read_namespaced_secret = AsyncMock(return_value=db_secret_mock)
    api_client_mock.list_namespaced_secret = AsyncMock(return_value=list_secret_return)
    api_client_mock.patch_namespaced_secret = AsyncMock()
    api_client_mock.delete_namespaced_secret = AsyncMock()

    orig_obj = KubernetesClient(AsyncMock())
    orig_obj.api_client = api_client_mock

    # v1_instance = AsyncMock(name="main_instance_v1", wraps=orig_obj)
    v1_instance = AsyncMock(name="main_instance_v1")
    v1_instance.api_client = api_client_mock
    v1_instance.create_secret.side_effect = orig_obj.create_secret
    v1_instance.encode_secret_value = orig_obj.encode_secret_value
    v1_instance.decode_secret_value = orig_obj.decode_secret_value
    v1_instance.is_pod_ready = AsyncMock()
    v1_instance.cp_from_pod = AsyncMock(return_value="tests/files/results.zip")

    return v1_instance

@fixture
def v1_ds_mock(mocker, mock_args_k8s):
    return mocker.patch(
        'app.models.dataset.KubernetesClient.create',
        name="v1_ds_mock",
        return_value=mock_args_k8s
    )

@fixture
def v1_ds_service_mock(mocker, mock_args_k8s):
    return mocker.patch(
        'app.services.datasets.KubernetesClient.create',
        name="v1_ds_service_mock",
        return_value=mock_args_k8s
    )

@fixture
def v1_task_mock(mocker, mock_args_k8s, v1_ds_mock):
    return mocker.patch(
        'app.helpers.task_pod.KubernetesClient.create',
        name="v1_task_mock",
        return_value=mock_args_k8s
    )

@fixture
def v1_registry_mock(mocker, mock_args_k8s, registry_secret_mock):
    mock_args_k8s.api_client.read_namespaced_secret = AsyncMock(return_value=registry_secret_mock)
    return mocker.patch(
        'app.models.registry.KubernetesClient.create',
        name="v1_registry_mock",
        return_value=mock_args_k8s
    )

@fixture
def v1_mock(mocker, mock_args_k8s):
    return mocker.patch(
        'app.helpers.kubernetes.KubernetesClient',
        name="v1_mock",
        return_value=mock_args_k8s
    )

@fixture
def mock_args_batch_k8s(pod_listed) -> AsyncMock:
    api_client_mock = AsyncMock(name="api_client")
    api_client_mock.create_namespaced_pod = AsyncMock()

    v1_batch_instance = AsyncMock(name="main_instance_v1")
    v1_batch_instance.api_client = api_client_mock
    v1_batch_instance.create_job_spec = Mock(spec=V1Job)
    return v1_batch_instance

@fixture
def v1_batch_mock(mocker, mock_args_batch_k8s) -> dict[str, Any]:
    return mocker.patch(
        'app.helpers.kubernetes.KubernetesBatchClient.create',
        return_value=mock_args_batch_k8s
    )

@fixture
def mock_args_crd(task):
    crd_api_client_mock = AsyncMock(name="crd_api_client")
    crd_api_client_mock.list_cluster_custom_object = AsyncMock(return_value={
        "items": [{
            "metadata": {
                "name": "crd_name",
                "annotations": {
                    f"{CRD_DOMAIN}/task_id": str(task.id)
                }
            }
        }]
    })
    v1_instance = AsyncMock(name="main_instance_v1")
    v1_instance.api_client = crd_api_client_mock
    v1_instance.api_client.patch_cluster_custom_object=AsyncMock()
    v1_instance.api_client.create_cluster_custom_object=AsyncMock()
    v1_instance.api_client.get_cluster_custom_object=AsyncMock(return_value={
        "metadata": {
            "annotations": {}
        }
    })
    return v1_instance

@fixture
def v1_crd_mock(mocker, mock_args_crd):
    return mocker.patch(
        "app.models.task.KubernetesCRDClient.create",
        return_value=mock_args_crd
    )


@fixture
def k8s_client(v1_mock, v1_batch_mock) -> dict:
    all_clients = {}
    all_clients.update({"v1": v1_mock})
    all_clients.update({"v1_batch": v1_batch_mock})
    return all_clients

@fixture
def dockerconfigjson_mock() -> dict[str, str]:
    contents = {"auths": {"acr.azurecr.io": {
        "username": "self.username",
        "password": "self.password",
        "email": "",
        "auth": "YWJjMTIz"
    }}}
    return {
        ".dockerconfigjson": base64.b64encode(json.dumps(contents).encode()).decode()
    }

# Dataset Mocking
@fixture
def dataset_post_body():
    return deepcopy(sample_ds_body)

@fixture
async def dataset(db_session) -> Dataset:
    dataset = Dataset(name="testds", host="example.com")
    await dataset.add(db_session)
    return dataset

@fixture
async def dataset_with_repo(db_session) -> Dataset:
    dataset = Dataset(name="testdsrepo", host="example.com", repository="organisation/repository")
    await dataset.add(db_session)
    return dataset

@fixture
async def dataset_oracle(db_session, mocker)  -> Dataset:
    mocker.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=True)
    dataset = Dataset(name="anotherds", host="example.com", password='pass', username='user', type="oracle")
    await dataset.add(db_session)
    return dataset

@fixture
async def catalogue(dataset, db_session) -> Catalogue:
    cat = Catalogue(dataset=dataset, title="new catalogue", description="shiny fresh data")
    await cat.add(db_session)
    return cat

@fixture
async def dictionary(db_session, dataset) -> List[Dictionary]:
    cat1 = Dictionary(dataset=dataset, description="Patient id", table_name="patients", field_name="id", label="p_id")
    cat2 = Dictionary(dataset=dataset, description="Patient info", table_name="patients", field_name="name", label="p_name")
    await cat1.add(db_session)
    await cat2.add(db_session)
    return [cat1, cat2]

@fixture
async def task(db_session, user_uuid, dataset, container) -> Task:
    task = Task(
        dataset_id=dataset.id,
        docker_image=container.full_image_name(),
        name="testTask",
        executors=[
            {
                "image": container.full_image_name()
            }
        ],
        description="test task",
        requested_by=user_uuid
    )
    await task.add(db_session)
    return task

@fixture
async def task_oracle(db_session, user_uuid, dataset_oracle, container) -> Task:
    task = Task(
        dataset_id=dataset_oracle.id,
        docker_image=container.full_image_name(),
        name="testTask",
        executors=[
            {
                "image": container.full_image_name()
            }
        ],
        description="test task",
        requested_by=user_uuid
    )
    await task.add(db_session)
    return task

@fixture
def dar_user():
    return "some@test.com"

@fixture
async def access_request(db_session, dataset, user_uuid, k8s_client):
    request = RequestModel(
        title="TestRequest",
        project_name="example.com",
        requested_by=user_uuid,
        dataset=dataset,
        proj_start=dt.now().date(),
        proj_end=(dt.now().date() + timedelta(days=10))
    )
    await request.add(db_session)
    return request

# Conditional url side_effects
def side_effect(dict_mock:dict):
    """
    This tries to mock dynamically according to what urllib3.requests
    receives as args returning a default 200 response body with an empty body

    :param dict_mock: should include the following keys
        - url:str       (required): portion of the requested url to mock
        - method:str    (optional): request method, defaults to GET
        - status:int    (optional): response status_code, defaults to 200
        - body:bytes    (optional): response body, defaults to an empty bytes string
    """
    def _url_side_effects(*args, **kwargs):
        """
        args:
        [0] -> method
        [1] -> url
        """
        default_body = ''.encode()
        method, url = args
        if dict_mock['url'] in url and dict_mock.get('method', 'GET') == method:
            return Mock(
                status=dict_mock.get('status', 200), data=dict_mock.get('body', default_body)
            )
        return Mock(
            status=200, data=default_body
        )
    return _url_side_effects

@fixture
def request_object_init(dataset: Dataset)-> dict[str, Any]:
    return {
        "title": "TestRequest",
        "dataset_id": dataset.id,
        "project_name": "project1",
        "requested_by": { "email": "test@test.com" },
        "description": "First task ever!",
        "proj_start": dt.now().date(),
        "proj_end": (dt.now().date() + timedelta(days=10))
    }

@fixture
def request_base_body(request_object_init):
    json_body = deepcopy(request_object_init)
    json_body["proj_start"] = json_body["proj_start"].strftime("%Y-%m-%d")
    json_body["proj_end"] = json_body["proj_end"].strftime("%Y-%m-%d")
    return json_body

@fixture
def request_base_body_name(request_base_body, dataset:Dataset)-> dict[str, Any]:
    json_body = deepcopy(request_base_body)
    json_body.pop("dataset_id")
    json_body["dataset_name"] = dataset.name
    return json_body

@fixture
def approve_request(mocker):
    return mocker.patch(
        'app.routes.datasets.RequestModel.approve',
        return_value={"token": "somejwttoken"}
    )

@fixture
def new_user_email():
    return "test@test.com"

@fixture
def new_user(new_user_email):
    return {"email": new_user_email, "id": "8b707136-a2d8-4b69-9ab5-ec341011a62f", "username": new_user_email}

@fixture
def set_task_other_delivery_env(mocker):
    mocker.patch('app.routes.admin.TASK_CONTROLLER', return_value="enabled")
    mocker.patch('app.routes.admin.OTHER_DELIVERY', return_value="url.delivery.com")

@fixture
def set_task_github_delivery_env(mocker):
    mocker.patch('app.routes.admin.TASK_CONTROLLER', return_value="enabled")
    mocker.patch('app.routes.admin.GITHUB_DELIVERY', return_value="org/repository")

@fixture
def decode_token_return(basic_user, user_uuid):
    decode_token_return = deepcopy(basic_user)
    decode_token_return["sub"] = user_uuid
    return decode_token_return

@fixture
def mock_keycloak_class(mocker, decode_token_return, basic_user):
    return mocker.patch(
        'app.services.datasets.Keycloak',
        return_value=Mock(
            get_client_id=Mock(return_value="client_id"),
            get_token=Mock(return_value="token"),
            get_policy=Mock(return_value={"id": "policy"}),
            get_scope=Mock(return_value={"id": "scope"}),
            decode_token=Mock(return_value=decode_token_return),
            get_user_by_email=Mock(return_value=basic_user),
            create_policy=Mock(return_value={"id": "policy"}),
            create_resource=Mock(return_value={"_id": "resource"}),
            create_permission=Mock(return_value={"id": "permission"}),
            is_token_valid=Mock(return_value=True)
        )
    )

@fixture(autouse=True)
def mock_kc_client(mocker, basic_user, decode_token_return, mock_keycloak_class, user_uuid):
    create_user_return = deepcopy(basic_user)
    create_user_return["password"] = "tempPassword!"
    kc_mock = {
        "main_kc": mocker.patch('app.routes.general.Keycloak', return_value=Mock(
            get_token=Mock(return_value={"access_token": "token"}),
        )),
        "wrappers_kc": mocker.patch('app.helpers.wrappers.Keycloak', return_value=Mock(
            get_token=Mock(return_value={"access_token": "token"}),
            decode_token=Mock(return_value=decode_token_return),
            get_user_by_email=Mock(return_value=basic_user),
            get_user_by_username=Mock(return_value=basic_user)
        )),
        "datasets_route_kc": mocker.patch('app.routes.datasets.Keycloak', return_value=Mock(
            get_token=Mock(return_value={"access_token": "token"}),
            get_admin_token=Mock(return_value={"access_token": "admin_token"}),
            decode_token=Mock(return_value=decode_token_return),
            get_user_by_email=Mock(return_value=basic_user),
            list_users=Mock(return_value=[basic_user]),
            create_user=Mock(return_value=create_user_return),
            get_user_role=Mock(return_value="Users"),
        )),
        "users_kc": mocker.patch('app.routes.users.Keycloak', return_value=Mock(
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
        "tasks_service_kc": mocker.patch('app.services.tasks.Keycloak', return_value=Mock(
            get_token=Mock(return_value={"access_token": "token"}),
            get_admin_token=Mock(return_value={"access_token": "admin_token"}),
            decode_token=Mock(return_value=decode_token_return),
            get_user_by_email=Mock(return_value=basic_user),
            get_user_by_id=Mock(return_value=basic_user),
            list_users=Mock(return_value=[basic_user]),
            create_user=Mock(return_value=create_user_return),
            get_user_role=Mock(return_value="Users"),
        )),
        "tasks_api_kc": mocker.patch('app.routes.tasks.Keycloak', return_value=Mock(
            get_token=Mock(return_value={"access_token": "token"}),
            get_admin_token=Mock(return_value={"access_token": "admin_token"}),
            decode_token=Mock(return_value=decode_token_return),
            get_user_by_email=Mock(return_value=basic_user),
            get_user_by_id=Mock(return_value=basic_user),
            list_users=Mock(return_value=[basic_user]),
            create_user=Mock(return_value=create_user_return),
            get_user_role=Mock(return_value="Users"),
        )),
        "request_schema_kc": mocker.patch('app.schemas.requests.Keycloak', return_value=Mock(
            get_user_by_email=Mock(return_value={"id": user_uuid})
        ))
    }
    return kc_mock
