import base64
import json
from copy import deepcopy
from typing import List
from pytest import fixture
from datetime import datetime as dt, timedelta
from kubernetes.client import V1Pod, V1Secret
from sqlalchemy.orm.session import close_all_sessions
from unittest.mock import Mock

from app import create_app
from app.helpers.base_model import db
from app.models.dataset import Dataset
from app.models.catalogue import Catalogue
from app.models.dictionary import Dictionary
from app.models.request import Request
from app.models.task import Task
from app.helpers.exceptions import KeycloakError
from app.helpers.const import CRD_DOMAIN


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
        "create_namespaced_pod_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.create_namespaced_pod'
        ),
        "create_persistent_volume_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.create_persistent_volume'
        ),
        "create_namespaced_persistent_volume_claim_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.create_namespaced_persistent_volume_claim'
        ),
        "read_namespaced_secret_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.read_namespaced_secret'
        ),
        "list_namespaced_secret_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.list_namespaced_secret'
        ),
        "patch_namespaced_secret_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.patch_namespaced_secret'
        ),
        "delete_namespaced_secret_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.delete_namespaced_secret'
        ),
        "create_namespaced_secret_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.create_namespaced_secret'
        ),
        "list_namespaced_pod_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.list_namespaced_pod'
        ),
        "delete_namespaced_pod_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.delete_namespaced_pod'
        ),
        "is_pod_ready_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.is_pod_ready'
        ),
        "read_namespaced_pod_log": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.read_namespaced_pod_log',
            return_value="Example logs\nanother line"
        ),
        "cp_from_pod_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.cp_from_pod',
            return_value="../tests/files/results.zip"
        )
    }

@fixture
def v1_batch_mock(mocker):
    return {
        "create_namespaced_job_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesBatchClient.create_namespaced_job'
        ),
        "delete_job_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesBatchClient.delete_job'
        )
    }

@fixture
def v1_crd_mock(mocker, task):
    return mocker.patch(
        "app.models.task.KubernetesCRDClient",
        return_value=Mock(
            list_cluster_custom_object=Mock(
                return_value={"items": [{
                    "metadata": {
                        "name": "crd_name",
                        "annotations": {
                            f"{CRD_DOMAIN}/task_id": str(task.id)
                        }
                    }
                }]
            },
            patch_cluster_custom_object=Mock(),
            create_cluster_custom_object=Mock(),
            get_cluster_custom_object=Mock()
            )
        )
    )

@fixture
def pod_listed(image_name):
    pod = Mock(name="default_pod", spec=V1Pod)
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
    return Mock(items=[pod])

@fixture
def secret_listed():
    secret = Mock(spec=V1Secret)
    secret.metadata.name = "url.delivery.com"
    secret.metadata.labels = {"url": "url.delivery.com"}
    secret.data = {"auth": "originalSecret"}
    return Mock(items=[secret])

@fixture
def k8s_client(secret_listed, pod_listed, v1_mock, v1_batch_mock, k8s_config):
    all_clients = {}
    all_clients.update(v1_mock)
    all_clients.update(v1_batch_mock)
    all_clients["read_namespaced_secret_mock"].return_value.data = {
        "PGUSER": "YWJjMTIz",
        "PGPASSWORD": "YWJjMTIz",
        "USER": "YWJjMTIz",
        "TOKEN": "YWJjMTIz"
    }
    all_clients["list_namespaced_pod_mock"].return_value = pod_listed
    all_clients["list_namespaced_secret_mock"].return_value = secret_listed
    return all_clients

@fixture
def dockerconfigjson_mock():
    contents = {"auths": {"acr.azurecr.io": {
        "username": "self.username",
        "password": "self.password",
        "email": "",
        "auth": "YWJjMTIz"
    }}}
    return {
        ".dockerconfigjson": base64.b64encode(json.dumps(contents).encode()).decode()
    }

@fixture
def reg_k8s_client(k8s_client, dockerconfigjson_mock):
    k8s_client["read_namespaced_secret_mock"].return_value.data.update(dockerconfigjson_mock)
    return k8s_client

# Dataset Mocking
@fixture()
def dataset_post_body():
    return deepcopy(sample_ds_body)

@fixture
def dataset(client, user_uuid, k8s_client, mock_kc_client) -> Dataset:
    dataset = Dataset(name="TestDs", host="example.com")
    dataset.add()
    return dataset

@fixture
def dataset_with_repo(client, user_uuid, k8s_client, mock_kc_client) -> Dataset:
    dataset = Dataset(name="TestDsRepo", host="example.com", repository="organisation/repository")
    dataset.add()
    return dataset

@fixture
def dataset_oracle(mocker, client, user_uuid, k8s_client)  -> Dataset:
    mocker.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=True)
    dataset = Dataset(name="AnotherDS", host="example.com", password='pass', username='user', type="oracle")
    dataset.add()
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
def task(user_uuid, dataset, container) -> Task:
    task = Task(
        dataset=dataset,
        docker_image=container.full_image_name(),
        name="testTask",
        executors=[
            {
                "image": container.full_image_name()
            }
        ],
        requested_by=user_uuid
    )
    task.add()
    return task

@fixture
def dar_user():
    return "some@test.com"

@fixture
def access_request(dataset, user_uuid, k8s_client):
    request = Request(
        title="TestRequest",
        project_name="example.com",
        requested_by=user_uuid,
        dataset=dataset,
        proj_start=dt.now().date().strftime("%Y-%m-%d"),
        proj_end=(dt.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
    )
    request.add()
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
def request_base_body(dataset):
    return {
        "title": "TestRequest",
        "dataset_id": dataset.id,
        "project_name": "project1",
        "requested_by": { "email": "test@test.com" },
        "description": "First task ever!",
        "proj_start": dt.now().date().strftime("%Y-%m-%d"),
        "proj_end": (dt.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
    }

@fixture
def request_base_body_name(dataset):
    return {
        "title": "Test Task",
        "dataset_name": dataset.name,
        "project_name": "project1",
        "requested_by": { "email": "test@test.com" },
        "description": "First task ever!",
        "proj_start": dt.now().date().strftime("%Y-%m-%d"),
        "proj_end": (dt.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
    }

@fixture
def approve_request(mocker):
    return mocker.patch(
        'app.datasets_api.Request.approve',
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
    mocker.patch('app.admin_api.TASK_CONTROLLER', return_value="enabled")
    mocker.patch('app.admin_api.OTHER_DELIVERY', return_value="url.delivery.com")

@fixture
def set_task_github_delivery_env(mocker):
    mocker.patch('app.admin_api.TASK_CONTROLLER', return_value="enabled")
    mocker.patch('app.admin_api.GITHUB_DELIVERY', return_value="org/repository")

@fixture
def mock_keycloak_class(mocker):
    return mocker.patch(
        'app.services.datasets.Keycloak',
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
            get_user_by_username=Mock(return_value=basic_user)
        )),
        "datasets_api_kc": mocker.patch('app.datasets_api.Keycloak', return_value=Mock(
            get_token=Mock(return_value={"access_token": "token"}),
            get_admin_token=Mock(return_value={"access_token": "admin_token"}),
            decode_token=Mock(return_value=decode_token_return),
            get_user_by_email=Mock(return_value=basic_user),
            list_users=Mock(return_value=[basic_user]),
            create_user=Mock(return_value=create_user_return),
            get_user_role=Mock(return_value="Users"),
        )),
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
        "tasks_schema_kc": mocker.patch('app.schemas.tasks.Keycloak', return_value=Mock(
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
