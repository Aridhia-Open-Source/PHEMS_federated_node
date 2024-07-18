"""
We are not aiming to test ALL methods here, such as the
    spec constructors (V1JobTemplateSpec, V1JobSpec, etc)
We want to test the creation, deletion and list operations.
    Those are network dependent as they are k8s REST API calls.
    - create_namespaced_pod
    - list_namespaced_pod
    - delete_namespaced_pod
    - create_namespaced_job
"""

import json
from tarfile import ReadError
import pytest
from kubernetes.client.exceptions import ApiException
from unittest import mock
from unittest.mock import Mock

from app.helpers.exceptions import InvalidRequest, KubernetesException
from app.helpers.kubernetes import KubernetesClient, KubernetesBatchClient
from tests.conftest import side_effect

@pytest.fixture
def pod_dict():
    return {
        "name": "pod_name",
        "image": "image",
        "labels": {
            "task_id": 1
        },
        "env_from": "db_secret",
        "command": "cmd",
        "mount_path": "/mnt"
    }

@pytest.fixture
def job_dict():
    return {
        "name": "job_name",
        "persistent_volumes": [],
        "labels": {}
    }

@mock.patch('urllib3.PoolManager')
def test_create_pod(
    url_mock,
    pod_dict,
    k8s_config
):
    """
    Test a successful pod is created with no exception raised
    """
    response_k8s_api = json.dumps({"name": 'podname'}).encode()
    namespace = 'tasks'
    k8s = KubernetesClient()
    url_mock.return_value.request.side_effect = side_effect(
        {"url": f"/namespaces/{namespace}/pod", "status": 400, "body": response_k8s_api}
    )
    k8s.create_namespaced_pod(namespace=namespace, body=k8s.create_pod_spec(pod_dict))

@mock.patch('urllib3.PoolManager')
def test_create_pod_failures(
    url_mock,
    k8s_config,
    pod_dict,
    mocker
):
    """
    Test a successful pod is created with no exception raised
    """
    k8s = KubernetesClient()
    namespace = 'tasks'
    side_effect_args = {
        "url": f"/namespaces/{namespace}/pod",
        "status": 404,
        "body": ''.encode(),
        "method": "POST"
    }
    url_mock.return_value.request.side_effect = side_effect(side_effect_args)

    with pytest.raises(ApiException):
        k8s.create_namespaced_pod(namespace=namespace, body=k8s.create_pod_spec(pod_dict))

    side_effect_args['status'] = 500
    url_mock.return_value.request.side_effect = side_effect(side_effect_args)
    with pytest.raises(ApiException):
        k8s.create_namespaced_pod(namespace=namespace, body=k8s.create_pod_spec(pod_dict))

@mock.patch('urllib3.PoolManager')
def test_create_job(
    url_mock,
    k8s_config,
    job_dict
    ):
    """
    Test a successful job is created with no exception raised
    """
    response_k8s_api = json.dumps({"name": 'jobname'}).encode()
    k8s = KubernetesBatchClient()
    namespace = "tasks"
    url_mock.return_value.request.side_effect = side_effect({
        "url": f"/namespaces/{namespace}/pod",
        "body": response_k8s_api
    })
    k8s.create_namespaced_job(namespace=namespace, body=k8s.create_job_spec(job_dict))

@mock.patch('urllib3.PoolManager')
def test_list_pods(url_mock, k8s_config):
    """
    Test a successful fetching of a list of pods is returned
        with no exception raised
    """
    response_k8s_api = json.dumps({"items": []}).encode()
    k8s = KubernetesClient()
    namespace = "tasks"
    url_mock.return_value.request.side_effect = side_effect({
        "url": f"/namespaces/{namespace}/pod",
        "body": response_k8s_api
    })
    assert k8s.list_namespaced_pod(namespace).items == []

@mock.patch('urllib3.PoolManager')
def test_delete_pods(url_mock, k8s_config):
    """
    Test a successful fetching of a list of pods is returned
        with no exception raised
    """
    k8s = KubernetesClient()
    namespace = "tasks"
    url_mock.return_value.request.side_effect = side_effect({
        "url": f"/namespaces/{namespace}/pod"
    })
    k8s.delete_pod('pod', namespace)

@mock.patch('urllib3.PoolManager')
def test_delete_pods_failures(url_mock, k8s_config):
    """
    Test a unsuccessful pod deletion with a pod not found
        no exception is raised, but it does on any other failure
    """
    k8s = KubernetesClient()
    namespace = "tasks"
    url_mock.return_value.request.side_effect = side_effect({
        "url": f"/namespaces/{namespace}/pods/pod",
        "method": "DELETE",
        "status": 404
    })
    k8s.delete_pod('pod', namespace)

    url_mock.return_value.request.side_effect = side_effect({
        "url": f"/namespaces/{namespace}/pods/pod",
        "method": "DELETE",
        "status": 500
    })
    with pytest.raises(InvalidRequest):
        k8s.delete_pod('pod', namespace)

@mock.patch('kubernetes.stream.ws_client.WSClient')
def test_cp_from_pod(ws_mock, mocker, k8s_config):
    """
    Tests the successful behaviour of cp_from_pod
    """
    ws_mock.return_value = Mock(
        is_open=Mock(side_effect=[True, False]),
        read_stdout=Mock(side_effect=['something']),
        peek_stderr=Mock(return_value=False),
        read_stderr=Mock(return_value='')
    )
    mocker.patch('app.helpers.kubernetes.tarfile').__enter__.return_value = Mock()
    mocker.patch('app.helpers.kubernetes.TemporaryFile').__enter__.return_value = Mock()

    k8s = KubernetesClient()
    assert k8s.cp_from_pod("pod_name", "/mnt", "/mnt") == '/mnt/results.tar.gz'

@mock.patch('kubernetes.stream.ws_client.WSClient')
def test_cp_from_pod_fails_tar_creation(ws_mock, mocker, k8s_config):
    """
    Tests the successful behaviour of cp_from_pod
    """
    ws_mock.return_value = Mock(
        is_open=Mock(side_effect=[True, False]),
        read_stdout=Mock(side_effect=['something']),
        peek_stderr=Mock(return_value=False),
        read_stderr=Mock(return_value='')
    )
    mocker.patch('app.helpers.kubernetes.tarfile.open').side_effect = ReadError('file could not be opened successfully')
    mocker.patch('app.helpers.kubernetes.TemporaryFile').__enter__.return_value = Mock()

    k8s = KubernetesClient()
    with pytest.raises(KubernetesException):
        k8s.cp_from_pod("pod_name", "/mnt", "/mnt") == '/mnt/results.tar.gz'
