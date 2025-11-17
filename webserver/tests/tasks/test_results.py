from datetime import timedelta
from kubernetes.client.exceptions import ApiException

from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *
from app.helpers.const import CLEANUP_AFTER_DAYS, CRD_DOMAIN


class TestTaskResults:
    def test_get_results(
        self,
        cr_client,
        registry_client,
        simple_admin_header,
        client,
        results_job_mock,
        task_mock
    ):
        """
        A simple test with mocked PVs to test a successful result
        fetch
        """
        response = client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.content_type == "application/zip"

    def test_get_results_job_creation_failure(
        self,
        cr_client,
        registry_client,
        simple_admin_header,
        client,
        reg_k8s_client,
        results_job_mock,
        task_mock
    ):
        """
        Tests that the job creation to fetch results from a PV returns a 500
        error code
        """
        # Get results - creating a job fails
        reg_k8s_client["create_namespaced_job_mock"].side_effect = ApiException(status=500, reason="Something went wrong")

        response = client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == 'Failed to run pod: Something went wrong'

    def test_results_not_found_with_expired_date(
        self,
        simple_admin_header,
        client,
        task_mock
    ):
        """
        A task result are being deleted after a declared number of days.
        This test makes sure an error is returned as expected
        """
        task_mock.created_at -= timedelta(days=CLEANUP_AFTER_DAYS)
        response = client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 500
        assert response.json["error"] == 'Tasks results are not available anymore. Please, run the task again'


class TestResultsReview:
    def test_default_review_status(
        self,
        simple_admin_header,
        client,
        task_mock,
        set_task_review_env
    ):
        """
        Test to make sure the default value is None,
        and the correct task description is correct
        """
        response = client.get(
            f'/tasks/{task_mock.id}',
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.json["review_status"] == "Pending Review"

    def test_review_approved(
        self,
        simple_admin_header,
        simple_user_header,
        client,
        task_mock,
        results_job_mock,
        k8s_client,
        set_task_review_env,
        v1_crd_mock,
        mocker
    ):
        """
        Test to make sure the approval allows the user
        to retrieve their results
        """
        mocker.patch(
            "app.models.task.Task.get_task_crd",
            return_value=None
        )
        response = client.post(
            f'/tasks/{task_mock.id}/results/approve',
            headers=simple_admin_header
        )
        assert response.status_code == 201
        v1_crd_mock.return_value.patch_cluster_custom_object.assert_not_called()

        response = client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_user_header
        )
        assert response.status_code == 200

    def test_task_from_controller_review_approved(
        self,
        simple_admin_header,
        client,
        task_mock,
        set_task_review_env,
        set_task_controller_env,
        v1_crd_mock,
        mocker
    ):
        """
        Test to make sure the approval allows the task controller CRD
        to be updated, and the results to be delivered
        """
        mocker.patch(
            "app.models.task.Task.get_task_crd",
            return_value={"metadata": {"annotations": {}}}
        )
        response = client.post(
            f'/tasks/{task_mock.id}/results/approve',
            headers=simple_admin_header
        )
        assert response.status_code == 201
        v1_crd_mock.return_value.patch_cluster_custom_object.assert_called()

    def test_admin_review_pending(
        self,
        simple_admin_header,
        client,
        results_job_mock,
        task_mock,
        set_task_review_env
    ):
        """
        Test to make sure the admin can fetch their results
        before the review took place
        """
        response = client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.content_type == "application/zip"

    def test_default_review_pending(
        self,
        simple_user_header,
        client,
        task_mock,
        set_task_review_env
    ):
        """
        Test to make sure the user can't fetch their results
        before the review took place
        """
        response = client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_user_header
        )
        assert response.status_code == 400
        assert response.json["status"] == "Pending Review"

    def test_review_blocked(
        self,
        simple_admin_header,
        simple_user_header,
        client,
        task_mock,
        results_job_mock,
        k8s_client,
        set_task_review_env,
        v1_crd_mock,
        mocker
    ):
        """
        Test to make sure the user can't fetch their results
        if they have been blocked by an administrator
        """
        mocker.patch(
            "app.models.task.Task.get_task_crd",
            return_value={
                "metadata": {
                    "name": "crd_name",
                    "annotations": {
                        f"{CRD_DOMAIN}/task_id": str(task_mock.id)
                    }
                }
            }
        )
        response = client.post(
            f'/tasks/{task_mock.id}/results/block',
            headers=simple_admin_header
        )
        assert response.status_code == 201

        response = client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_user_header
        )
        assert response.status_code == 400
        assert response.json["status"] == "Blocked Release"

    def test_review_task_not_found(
        self,
        simple_user_header,
        client,
        task_mock,
        set_task_review_env
    ):
        """
        Trying to review an non-existing task should return 404
        """
        response = client.get(
            f'/tasks/{task_mock.id + 1}/results',
            headers=simple_user_header
        )
        assert response.status_code == 404
        assert response.json["error"] == f"Task with id {task_mock.id + 1} does not exist"

    def test_review_twice(
        self,
        simple_admin_header,
        client,
        task_mock,
        k8s_client,
        set_task_review_env,
        v1_crd_mock,
        mocker
    ):
        """
        Tests that review can only happen once
        """
        mocker.patch(
            "app.models.task.Task.get_task_crd",
            return_value={
                "metadata": {
                    "name": "crd_name",
                    "annotations": {
                        f"{CRD_DOMAIN}/task_id": str(task_mock.id)
                    }
                }
            }
        )
        response = client.post(
            f'/tasks/{task_mock.id}/results/block',
            headers=simple_admin_header
        )
        assert response.status_code == 201
        response = client.post(
            f'/tasks/{task_mock.id}/results/approve',
            headers=simple_admin_header
        )
        assert response.status_code == 400
        assert response.json['error'] == "Task has been already reviewed"

    def test_review_crd_patch_error(
        self,
        simple_admin_header,
        client,
        task_mock,
        k8s_crd_500,
        set_task_review_env,
        v1_crd_mock,
        mocker
    ):
        """
        Tests that review fails when the CRD is not found
        """
        mocker.patch(
            "app.models.task.Task.get_task_crd",
            return_value={"metadata": {"annotations": {}}}
        )
        v1_crd_mock.return_value.patch_cluster_custom_object.side_effect = k8s_crd_500

        response = client.post(
            f'/tasks/{task_mock.id}/results/approve',
            headers=simple_admin_header
        )
        assert response.status_code == 500
        v1_crd_mock.return_value.patch_cluster_custom_object.assert_called()

        assert response.json['error'] == "Could not activate automatic delivery"

    def test_review_crd_not_found(
        self,
        simple_admin_header,
        client,
        task_mock,
        k8s_crd_404,
        set_task_review_env,
        v1_crd_mock
    ):
        """
        Tests that if a task without a CRD will go through
        normal process without calling patch_cluster_custom_object_mock
        """
        v1_crd_mock.return_value.get_cluster_custom_object.side_effect = k8s_crd_404

        response = client.post(
            f'/tasks/{task_mock.id}/results/block',
            headers=simple_admin_header
        )
        assert response.status_code == 201
        v1_crd_mock.return_value.patch_cluster_custom_object.assert_not_called()

    def test_review_disabled(
        self,
        simple_admin_header,
        client,
        task_mock
    ):
        """
        Tests that review cannot be used when the env var
        TASK_REVIEW is not set (set_task_review_env fixture does that)
        """
        for review in ["block", "approve"]:
            response = client.post(
                f'/tasks/{task_mock.id}/results/{review}',
                headers=simple_admin_header
            )
            assert response.status_code == 400
            assert response.json['error'] == "The Task Review feature is not available on this Federated Node"
