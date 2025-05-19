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
import pytest
from kubernetes import client
from kubernetes.client.exceptions import ApiException
from tarfile import ReadError
from unittest import mock
from unittest.mock import Mock

from app.helpers.exceptions import InvalidRequest, KubernetesException
from app.helpers.kubernetes import KubernetesClient, KubernetesBatchClient
from tests.conftest import side_effect
from app.helpers.task_pod import TaskPod

@pytest.fixture
def pod_dict(dataset):
    return {
        "name": "pod_name",
        "image": "image",
        "labels": {
            "task_id": 1
        },
        "dataset": dataset,
        "dry_run": "false",
        "env_from": [],
        "command": "cmd",
        "mount_path": {"folder1": "/mnt"},
        "input_path": {"input.csv": "/mnt"},
        "environment": {},
        "resources": {},
        "db_query": {
            "query": "SELECT * FROM table",
            "dialect": "postgres"
        }
    }

@pytest.fixture
def job_dict():
    return {
        "name": "job_name",
        "persistent_volumes": [],
        "labels": {}
    }

class TestKubernetesHelper:
    @mock.patch('urllib3.PoolManager')
    def test_create_pod(
        self,
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
        # Restore the original k8s method
        k8s.create_namespaced_pod = client.CoreV1Api().create_namespaced_pod

        url_mock.return_value.request.side_effect = side_effect(
            {"url": f"/namespaces/{namespace}/pod", "status": 400, "body": response_k8s_api}
        )
        k8s.create_namespaced_pod(namespace=namespace, body=TaskPod(**pod_dict).create_pod_spec())

    @mock.patch('urllib3.PoolManager')
    def test_create_pod_failures(
        self,
        url_mock,
        k8s_config,
        pod_dict
    ):
        """
        Test a successful pod is created with no exception raised
        """
        k8s = KubernetesClient()
        # Restore the original k8s method
        k8s.create_namespaced_pod = client.CoreV1Api().create_namespaced_pod
        namespace = 'tasks'
        side_effect_args = {
            "url": f"/namespaces/{namespace}/pod",
            "status": 404,
            "body": ''.encode(),
            "method": "POST"
        }
        url_mock.return_value.request.side_effect = side_effect(side_effect_args)

        with pytest.raises(ApiException):
            k8s.create_namespaced_pod(namespace=namespace, body=TaskPod(**pod_dict).create_pod_spec())

        side_effect_args['status'] = 500
        url_mock.return_value.request.side_effect = side_effect(side_effect_args)
        with pytest.raises(ApiException):
            k8s.create_namespaced_pod(namespace=namespace, body=TaskPod(**pod_dict).create_pod_spec())

    @mock.patch('urllib3.PoolManager')
    def test_create_job(
        self,
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
    def test_list_pods(
        self,
        url_mock,
        k8s_config
    ):
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
    def test_delete_pods(
        self,
        url_mock,
        k8s_config
    ):
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
    def test_delete_pods_failures(
        self,
        url_mock,
        k8s_config
    ):
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
    def test_cp_from_pod(
        self,
        ws_mock,
        mocker,
        k8s_config
    ):
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
    def test_cp_from_pod_fails_tar_creation(
        self,
        ws_mock,
        mocker,
        k8s_config
    ):
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
