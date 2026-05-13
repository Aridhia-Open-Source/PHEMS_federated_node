from unittest import mock
from app.helpers.task_pod import TaskPod

class TestTaskPod:
    def test_task_pod_pv_mount_options(self, dataset, pod_dict):
        """
        Test that mount options are correctly applied to the PV spec
        """
        with mock.patch("app.helpers.task_pod.MOUNT_OPTIONS", "idsfromsid,modefromsid"):
            task_pod = TaskPod(**pod_dict)
            task_pod.create_storage_specs()
            assert task_pod.pv.spec.mount_options == ["idsfromsid", "modefromsid"]

    def test_task_pod_pv_no_mount_options(self, dataset, pod_dict):
        """
        Test that no mount options are applied when the env var is not set
        """
        with mock.patch("app.helpers.task_pod.MOUNT_OPTIONS", None):
            task_pod = TaskPod(**pod_dict)
            task_pod.create_storage_specs()
            assert task_pod.pv.spec.mount_options is None

    def test_task_pod_pv_empty_mount_options(self, dataset, pod_dict):
        """
        Test that no mount options are applied when the env var is empty
        """
        with mock.patch("app.helpers.task_pod.MOUNT_OPTIONS", ""):
            task_pod = TaskPod(**pod_dict)
            task_pod.create_storage_specs()
            assert task_pod.pv.spec.mount_options is None
