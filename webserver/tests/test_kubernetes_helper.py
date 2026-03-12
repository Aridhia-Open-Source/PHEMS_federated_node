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

import errno
from aiohttp import WSMsgType
from pytest import mark, raises
from pytest_asyncio import fixture

from tarfile import ReadError
from unittest import mock
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from app.helpers.exceptions import KubernetesException
from app.helpers.kubernetes import KubernetesClient


@fixture
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
        },
        "regcred_secret": "acrsecret"
    }

@fixture
def job_dict():
    return {
        "name": "job_name",
        "persistent_volumes": [],
        "labels": {}
    }

class TestKubernetesHelper:
    @fixture
    def mock_ws_api_client(self):
        with patch('kubernetes_asyncio.stream.WsApiClient') as mock_class:
            mock_instance = AsyncMock(name="mock_ws_api_client")
            mock_class.return_value = mock_instance
            yield mock_instance

    @fixture
    def mock_v1_api_client(self):
        with patch('app.helpers.kubernetes.client.CoreV1Api') as mock_class:
            mock_instance = AsyncMock(name="mock_v1_api_client")

            close_msg = Mock()
            # Quit immediately
            close_msg.type = WSMsgType.CLOSE
            close_msg.data = b""
            ws_mock = AsyncMock(name="ws_stream")
            ws_mock.receive.return_value = close_msg

            context_manager_mock = MagicMock()
            context_manager_mock.__aenter__ = AsyncMock(return_value=ws_mock)
            context_manager_mock.__aexit__ = AsyncMock(return_value=False)

            mock_instance.connect_get_namespaced_pod_exec = AsyncMock(
                return_value=context_manager_mock
            )

            mock_class.return_value = mock_instance
            yield mock_instance

    @mark.asyncio
    async def test_cp_from_pod(
        self,
        mock_ws_api_client,
        mock_v1_api_client,
        mocker
    ):
        """
        Tests the successful behaviour of cp_from_pod
        """
        mocker.patch('app.helpers.kubernetes.shutil')
        mocker.patch('app.helpers.kubernetes.tarfile').__enter__.return_value = Mock()

        k8s = await KubernetesClient.create()
        assert await k8s.cp_from_pod("pod_name", "/mnt", "/mnt", "host-id-results") == '/tmp/data/host-id-results.zip'

    @mark.asyncio
    async def test_cp_from_pod_fails_temp_files_read(
        self,
        mocker,
        mock_ws_api_client,
        mock_v1_api_client,
    ):
        """
        Tests reading fails on cp_from_pod
        """
        mocker.patch('app.helpers.kubernetes.tarfile.open').side_effect = ReadError('file could not be opened successfully')

        k8s = await KubernetesClient.create()
        with raises(KubernetesException):
            await k8s.cp_from_pod("pod_name", "/mnt", "/mnt", "host-id-results") == '/mnt/host-id-results.tar.gz'

    @mark.asyncio
    async def test_cp_from_pod_fails_zip_creation(
        self,
        mock_ws_api_client,
        mock_v1_api_client,
        mocker,
    ):
        """
        Tests the archive creation fails
        """
        mocker.patch('app.helpers.kubernetes.shutil.make_archive').side_effect = NotADirectoryError(errno.ENOTDIR, 'Not a directory', 'path')

        k8s = await KubernetesClient.create()
        with raises(KubernetesException):
            await k8s.cp_from_pod("pod_name", "/mnt", "/mnt", "host-id-results") == '/mnt/host-id-results.zip'

    @mark.asyncio
    async def test_cp_from_pod_fails_zip_creation_other_exception(
        self,
        mock_ws_api_client,
        mock_v1_api_client,
        mocker,
    ):
        """
        Tests the archive creation fails
        """
        mocker.patch('app.helpers.kubernetes.shutil.make_archive').side_effect = KeyError()

        k8s = await KubernetesClient.create()
        with raises(KubernetesException):
            await k8s.cp_from_pod("pod_name", "/mnt", "/mnt", "host-id-results") == '/mnt/host-id-results.zip'
