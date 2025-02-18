import base64
import copy
import json
import os
import pytest
import requests
from datetime import datetime as dt, timedelta
from kubernetes.client import V1Pod
from sqlalchemy.orm.session import close_all_sessions
from unittest.mock import Mock

from app import create_app
from app.helpers.db import db
from app.models.dataset import Dataset
from app.models.request import Request
from app.helpers.keycloak import Keycloak, URLS, KEYCLOAK_SECRET, KEYCLOAK_CLIENT
from tests.helpers.keycloak import clean_kc
from app.helpers.exceptions import KeycloakError


sample_ds_body = {
    "name": "TestDs",
    "host": "db",
    "port": 5432,
    "username": "Username",
    "password": "pass",
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

@pytest.fixture
def image_name():
    return "example:latest"

@pytest.fixture
def user_token(basic_user):
    """
    Since calling Keycloak.get_impersonation_token is not
    viable as there is an "audience" conflict.
    All clients are hardcoded, as only global and the DAR clients
    are allowed to exchange tokens, not admin-cli.
    """
    admin_token = Keycloak().get_token(
        username=os.getenv("KEYCLOAK_ADMIN"),
        password=os.getenv("KEYCLOAK_ADMIN_PASSWORD"),
        token_type='access_token'
    )
    payload = {
        'client_secret': KEYCLOAK_SECRET,
        'client_id': KEYCLOAK_CLIENT,
        'grant_type': 'urn:ietf:params:oauth:grant-type:token-exchange',
        'requested_token_type': 'urn:ietf:params:oauth:token-type:refresh_token',
        'subject_token': admin_token,
        'requested_subject': basic_user["id"],
        'audience': 'global'
    }
    exchange_resp = requests.post(
        URLS["get_token"],
        data=payload,
        headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        }
    )
    return exchange_resp.json()["refresh_token"]

@pytest.fixture
def app_ctx(app):
    with app.app_context():
        yield

# Users' section
@pytest.fixture
def user_uuid():
    return Keycloak().get_user_by_username(os.getenv("KEYCLOAK_ADMIN"))["id"]

@pytest.fixture
def login_admin(client):
    return Keycloak().get_token(
        username=os.getenv("KEYCLOAK_ADMIN"),
        password=os.getenv("KEYCLOAK_ADMIN_PASSWORD")
    )

@pytest.fixture
def basic_user():
    return Keycloak().create_user(**{"email": "test@basicuser.com"})

@pytest.fixture
def login_user(client, basic_user, mocker):
    mocker.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=True)
    mocker.patch('app.helpers.wrappers.Keycloak.decode_token', return_value={"username": "test@basicuser.com", "sub": "123-123abc"})

    return Keycloak().get_impersonation_token(basic_user["id"])

@pytest.fixture
def project_not_found(mocker):
    return mocker.patch(
        'app.helpers.wrappers.Keycloak.exchange_global_token',
        side_effect=KeycloakError("Could not find project", 400)
    )

@pytest.fixture
def simple_admin_header(login_admin):
    return {"Authorization": f"Bearer {login_admin}"}

@pytest.fixture
def post_json_admin_header(login_admin):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {login_admin}"
    }

@pytest.fixture
def simple_user_header(user_token):
    return {"Authorization": f"Bearer {user_token}"}

@pytest.fixture
def post_json_user_header(user_token):
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {user_token}"
    }

@pytest.fixture
def post_form_admin_header(login_admin):
    return {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Bearer {login_admin}"
    }

# Flask client to perform requests
@pytest.fixture
def client():
    app = create_app()
    app.testing = True
    with app.test_client() as tclient:
        with app.app_context():
            db.create_all()
            yield tclient
            close_all_sessions()
            db.drop_all()
            clean_kc()

# K8s
@pytest.fixture
def k8s_config(mocker):
    mocker.patch('kubernetes.config.load_kube_config', return_value=Mock())
    mocker.patch('app.helpers.kubernetes.config.load_kube_config', Mock())

@pytest.fixture
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
        "cp_from_pod_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesClient.cp_from_pod',
            return_value="../tests/files/results.tar.gz"
        )
    }

@pytest.fixture
def v1_batch_mock(mocker):
    return {
        "create_namespaced_job_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesBatchClient.create_namespaced_job'
        ),
        "delete_job_mock": mocker.patch(
            'app.helpers.kubernetes.KubernetesBatchClient.delete_job'
        )
    }

@pytest.fixture
def pod_listed(mocker):
    pod = Mock(spec=V1Pod)
    pod.spec.containers = [Mock(image="some_image")]
    pod.status.container_statuses = [Mock(terminated=Mock())]
    return Mock(items=[pod])

@pytest.fixture
def k8s_client(mocker, pod_listed, v1_mock, v1_batch_mock, k8s_config):
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
    return all_clients

@pytest.fixture
def reg_k8s_client(k8s_client):
    k8s_client["read_namespaced_secret_mock"].return_value.data.update({
            ".dockerconfigjson": base64.b64encode("{\"auths\": {}}".encode()).decode()
        })
    return k8s_client

# Dataset Mocking
@pytest.fixture(scope='function')
def dataset_post_body():
    return copy.deepcopy(sample_ds_body)

@pytest.fixture
def dataset(mocker, client, user_uuid, k8s_client):
    mocker.patch('app.helpers.wrappers.Keycloak.is_token_valid', return_value=True)
    dataset = Dataset(name="TestDs", host="example.com", password='pass', username='user')
    dataset.add(user_id=user_uuid)
    return dataset

@pytest.fixture
def dataset2(client, user_uuid, k8s_client):
    dataset = Dataset(name="AnotherDS", host="example.com", password='pass', username='user')
    dataset.add(user_id=user_uuid)
    return dataset

@pytest.fixture
def dar_user():
    return "some@test.com"

@pytest.fixture
def access_request(client, dataset, user_uuid, k8s_client, dar_user):
    request = Request(
        title="TestRequest",
        project_name="example.com",
        requested_by=json.dumps({"email": dar_user}),
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

@pytest.fixture
def request_base_body(dataset):
    return {
        "title": "Test Task",
        "dataset_id": dataset.id,
        "project_name": "project1",
        "requested_by": { "email": "test@test.com" },
        "description": "First task ever!",
        "proj_start": dt.now().date().strftime("%Y-%m-%d"),
        "proj_end": (dt.now().date() + timedelta(days=10)).strftime("%Y-%m-%d")
    }

@pytest.fixture
def approve_request(mocker):
    return mocker.patch(
        'app.datasets_api.Request.approve',
        return_value={"token": "somejwttoken"}
    )

@pytest.fixture
def new_user_email():
    return "test@test.com"

@pytest.fixture
def new_user(new_user_email):
    return Keycloak().create_user(set_temp_pass=True, **{"email": new_user_email})
