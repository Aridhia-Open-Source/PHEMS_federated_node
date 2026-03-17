from pytest import mark
from datetime import timedelta
from kubernetes_asyncio.client.exceptions import ApiException
from sqlalchemy import update
from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *
from app.helpers.keycloak import Keycloak
from tests.base_test_class import BaseTest
from app.helpers.settings import settings


class TestTaskResults(BaseTest):
    @mark.asyncio
    async def test_get_results(
        self,
        registry_client,
        v1_batch_tasks_mock,
        simple_admin_header,
        client,
        results_job_mock,
        task_mock,
        mock_kc_client_task_model
    ):
        """
        A simple test with mocked PVs to test a successful result
        fetch
        """
        response = await client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"

    @mark.asyncio
    async def test_get_results_job_creation_failure(
        self,
        registry_client,
        simple_admin_header,
        client,
        v1_batch_tasks_mock,
        results_job_mock,
        mock_args_batch_k8s,
        task_mock,
        mock_kc_client_task_model
    ):
        """
        Tests that the job creation to fetch results from a PV returns a 500
        error code
        """
        # Get results - creating a job fails
        mock_args_batch_k8s.api_client.create_namespaced_job.side_effect = ApiException(status=500, reason="Something went wrong")

        response = await client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 400
        assert response.json()["error"] == 'Failed to run pod: Something went wrong'

    @mark.asyncio
    async def test_results_not_found_with_expired_date(
        self,
        simple_admin_header,
        client,
        task_mock,
        mock_kc_client_task_model
    ):
        """
        A task result are being deleted after a declared number of days.
        This test makes sure an error is returned as expected
        """
        await self.db_session.execute(
            update(Task).
            where(Task.id == task_mock.id).
            values({"created_at": task_mock.created_at - timedelta(days=settings.cleanup_after_days)})
        )

        response = await client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 500
        assert response.json()["error"] == 'Tasks results are not available anymore. Please, run the task again'


class TestResultsReview:
    @mark.asyncio
    async def test_default_review_status(
        self,
        simple_admin_header,
        client,
        task_mock,
        set_task_review_env,
        mock_kc_client_task_model
    ):
        """
        Test to make sure the default value is None,
        and the correct task description is correct
        """
        response = await client.get(
            f'/tasks/{task_mock.id}',
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.json()["review"] == "Pending Review"

    @mark.asyncio
    async def test_review_approved(
        self,
        simple_admin_header,
        simple_user_header,
        client,
        task_mock,
        results_job_mock,
        v1_batch_tasks_mock,
        set_task_review_env,
        v1_crd_mock,
        mocker,
        mock_kc_client_task_model
    ):
        """
        Test to make sure the approval allows the user
        to retrieve their results
        """
        mocker.patch(
            "app.models.task.Task.get_task_crd",
            return_value=None
        )
        response = await client.post(
            f'/tasks/{task_mock.id}/results/approve',
            headers=simple_admin_header
        )
        assert response.status_code == 201
        v1_crd_mock.api_client.patch_cluster_custom_object.assert_not_called()

        response = await client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_user_header
        )
        assert response.status_code == 200

    @mark.asyncio
    async def test_task_from_controller_review_approved(
        self,
        simple_admin_header,
        client,
        task_mock,
        set_task_review_env,
        set_task_controller_env,
        mock_args_crd,
        v1_crd_mock,
        mock_kc_client_task_model
    ):
        """
        Test to make sure the approval allows the task controller CRD
        to be updated, and the results to be delivered
        """
        response = await client.post(
            f'/tasks/{task_mock.id}/results/approve',
            headers=simple_admin_header
        )
        assert response.status_code == 201
        mock_args_crd.api_client.patch_cluster_custom_object.assert_called()

    @mark.asyncio
    async def test_admin_review_pending(
        self,
        simple_admin_header,
        client,
        results_job_mock,
        task_mock,
        set_task_review_env,
        mock_kc_client_task_model
    ):
        """
        Test to make sure the admin can fetch their results
        before the review took place
        """
        response = await client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_admin_header
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"

    @mark.asyncio
    async def test_default_review_pending(
        self,
        simple_user_header,
        client,
        task_mock,
        set_task_review_env,
        v1_crd_mock,
        mock_args_k8s,
        v1_task_mock,
        base_kc_mock_args,
        mock_kc_client_task_model
    ):
        """
        Test to make sure the user can't fetch their results
        before the review took place
        """
        base_kc_mock_args.is_user_admin.return_value = False
        mock_args_k8s.api_client.list_namespaced_pod.return_value.items[0].metadata.name = task_mock.name
        response = await client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_user_header
        )
        assert response.status_code == 400
        assert response.json()["status"] == "Pending Review"

    @mark.asyncio
    async def test_review_blocked(
        self,
        simple_admin_header,
        simple_user_header,
        client,
        task_mock,
        results_job_mock,
        k8s_client,
        set_task_review_env,
        v1_crd_mock,
        base_kc_mock_args,
        mocker,
        mock_kc_client_task_model
    ):
        """
        Test to make sure the user can't fetch their results
        if they have been blocked by an administrator
        """
        mocker.patch.object(Keycloak, "is_user_admin", return_value=False)
        mocker.patch(
            "app.models.task.Task.get_task_crd",
            return_value={
                "metadata": {
                    "name": "crd_name",
                    "annotations": {
                        f"{settings.crd_domain}/task_id": str(task_mock.id)
                    }
                }
            }
        )
        response = await client.post(
            f'/tasks/{task_mock.id}/results/block',
            headers=simple_admin_header
        )
        assert response.status_code == 201

        base_kc_mock_args.is_user_admin.return_value = False

        response = await client.get(
            f'/tasks/{task_mock.id}/results',
            headers=simple_user_header
        )
        assert response.status_code == 400
        assert response.json()["status"] == "Blocked Release"

    @mark.asyncio
    async def test_review_task_not_found(
        self,
        simple_user_header,
        client,
        task_mock,
        set_task_review_env,
        mock_kc_client_task_model
    ):
        """
        Trying to review an non-existing task should return 404
        """
        response = await client.get(
            f'/tasks/{task_mock.id + 1}/results',
            headers=simple_user_header
        )
        assert response.status_code == 404
        assert response.json()["error"] == f"Task with id {task_mock.id + 1} does not exist"

    @mark.asyncio
    async def test_review_twice(
        self,
        simple_admin_header,
        client,
        task_mock,
        k8s_client,
        set_task_review_env,
        v1_crd_mock,
        mocker,
        mock_kc_client_task_model
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
                        f"{settings.crd_domain}/task_id": str(task_mock.id)
                    }
                }
            }
        )
        response = await client.post(
            f'/tasks/{task_mock.id}/results/block',
            headers=simple_admin_header
        )
        assert response.status_code == 201
        response = await client.post(
            f'/tasks/{task_mock.id}/results/approve',
            headers=simple_admin_header
        )
        assert response.status_code == 400
        assert response.json()['error'] == "Task has been already reviewed"

    @mark.asyncio
    async def test_review_crd_patch_error(
        self,
        simple_admin_header,
        client,
        task_mock,
        k8s_crd_500,
        set_task_review_env,
        mock_args_crd,
        v1_crd_mock,
        mock_kc_client_task_model
    ):
        """
        Tests that review fails when the CRD is not found
        """
        mock_args_crd.api_client.patch_cluster_custom_object.side_effect = k8s_crd_500

        response = await client.post(
            f'/tasks/{task_mock.id}/results/approve',
            headers=simple_admin_header
        )
        assert response.status_code == 500
        mock_args_crd.api_client.patch_cluster_custom_object.assert_called()

        assert response.json()['error'] == "Could not activate automatic delivery"

    @mark.asyncio
    async def test_review_crd_not_found(
        self,
        simple_admin_header,
        client,
        task_mock,
        k8s_crd_404,
        set_task_review_env,
        v1_crd_mock,
        mock_kc_client_task_model
    ):
        """
        Tests that if a task without a CRD will go through
        normal process without calling patch_cluster_custom_object_mock
        """
        v1_crd_mock.return_value.get_cluster_custom_object.side_effect = k8s_crd_404

        response = await client.post(
            f'/tasks/{task_mock.id}/results/block',
            headers=simple_admin_header
        )
        assert response.status_code == 201
        v1_crd_mock.return_value.patch_cluster_custom_object.assert_not_called()

    @mark.asyncio
    async def test_review_disabled(
        self,
        simple_admin_header,
        client,
        task_mock,
        mock_kc_client_task_model
    ):
        """
        Tests that review cannot be used when the env var
        TASK_REVIEW is not set (set_task_review_env fixture does that)
        """
        for review in ["block", "approve"]:
            response = await client.post(
                f'/tasks/{task_mock.id}/results/{review}',
                headers=simple_admin_header
            )
            assert response.status_code == 400
            assert response.json()['error'] == "The Task Review feature is not available on this Federated Node"
