import json
from datetime import datetime as dt
from kubernetes.client import V1Pod
from kubernetes.client.exceptions import ApiException
from unittest.mock import Mock

from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *


class TestCronJobs:
    """
    Class to specifically check cron job features, so things like
    task ownership tests are already covered by the basic TestGetTasks
    """
    def test_create_cronjob(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            task_body
        ):
        """
        Tests cronjob creation returns 201
        """
        task_body["schedule"] = "0 12 * * *"
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 201
        reg_k8s_client["create_namespaced_cron_job_with_http_info"].assert_called()

    def test_create_cronjob_bad_cronrule(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            task_body
        ):
        """
        Tests task creation returns fails if cronrule is missformatted
        """
        task_body["schedule"] = "0 12 * *"
        reg_k8s_client["create_namespaced_cron_job_with_http_info"].side_effect = ApiException(
            http_resp=Mock(status=500, reason="Error", data=json.dumps({
                "details": {
                    "causes": [{
                    "message":"Invalid value: \"0 12 * *\": expected exactly 5 fields, found 4: [0 12 * *]"}]
                }
            }))
        )
        response = client.post(
            '/tasks/',
            data=json.dumps(task_body),
            headers=post_json_admin_header
        )
        assert response.status_code == 400

    def test_suspend_cronjob(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            cronjob
        ):
        """
        Tests successful cronjob suspension
        """
        reg_k8s_client["list_namespaced_cron_job"].return_value.items[0].spec.suspend = False
        response = client.patch(
            f'/tasks/{cronjob.id}/suspend',
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        reg_k8s_client["patch_namespaced_cron_job"].assert_called()

    def test_suspend_cronjob_unauth(
            self,
            cr_client,
            post_json_user_header,
            client,
            reg_k8s_client,
            registry_client,
            cronjob,
            mock_kc_client
        ):
        """
        Tests cronjob status management is not allowed for non admin users
        """
        mock_kc_client["wrappers_kc"].return_value.is_token_valid.return_value = False

        response = client.patch(
            f'/tasks/{cronjob.id}/suspend',
            headers=post_json_user_header
        )
        assert response.status_code == 403
        reg_k8s_client["patch_namespaced_cron_job"].assert_not_called()

        response = client.patch(
            f'/tasks/{cronjob.id}/resume',
            headers=post_json_user_header
        )
        assert response.status_code == 403
        reg_k8s_client["patch_namespaced_cron_job"].assert_not_called()

    def test_suspend_cronjob_already_suspended(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            cronjob
        ):
        """
        Tests failed cronjob suspension
        """
        reg_k8s_client["list_namespaced_cron_job"].return_value.items[0].spec.suspend = True
        response = client.patch(
            f'/tasks/{cronjob.id}/suspend',
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == "CronJob is already set to be suspended"
        reg_k8s_client["patch_namespaced_cron_job"].assert_not_called()

    def test_resume_cronjob(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            cronjob
        ):
        """
        Tests successful cronjob suspension
        """
        reg_k8s_client["list_namespaced_cron_job"].return_value.items[0].spec.suspend = True
        response = client.patch(
            f'/tasks/{cronjob.id}/resume',
            headers=post_json_admin_header
        )
        assert response.status_code == 202
        reg_k8s_client["patch_namespaced_cron_job"].assert_called()

    def test_resume_cronjob_already_active(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            cronjob
        ):
        """
        Tests failed cronjob suspension
        """
        reg_k8s_client["list_namespaced_cron_job"].return_value.items[0].spec.suspend = False
        response = client.patch(
            f'/tasks/{cronjob.id}/resume',
            headers=post_json_admin_header
        )
        assert response.status_code == 400
        assert response.json["error"] == "CronJob is already set to be enabled"
        reg_k8s_client["patch_namespaced_cron_job"].assert_not_called()

    def test_get_status_done(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            cronjob
    ):
        """
        Tests the cronjob status field is formatted correctly
        """
        reg_k8s_client["list_namespaced_job"].return_value.items[0].status = Mock(
            succeeded=1,
            failed=0,
            ready=0
        )
        response_logs = client.get(
            f'/tasks/{cronjob.id}',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 200
        assert response_logs.json["status"] == {
            "succeeded": 1,
            "ready": 0,
            "failed": 0
        }

    def test_get_results(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            cronjob
        ):
        """
        Tests that the result job is triggered for cron tasks
        """
        response_res = client.get(
            f'/tasks/{cronjob.id}/results',
            headers=post_json_admin_header
        )
        assert response_res.status_code == 200
        assert response_res.content_type == "application/zip"

    def test_get_results_cron_not_found(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            cronjob
        ):
        """
        Tests that results endpoint will return an error if the cronjob
        does not exist
        """
        reg_k8s_client["list_namespaced_cron_job"].return_value.items = []
        response_res = client.get(
            f'/tasks/{cronjob.id}/results',
            headers=post_json_admin_header
        )
        assert response_res.status_code == 500
        assert response_res.json["error"] == "CronJob not found"

    def test_logs_multiple_logs(
            self,
            cr_client,
            post_json_admin_header,
            client,
            reg_k8s_client,
            registry_client,
            cronjob
        ):
        """
        Tests that logs are presented with multiple pods
        """
        pods = []
        for i in range(2):
            p = Mock(name=f"pod_{i}", spec=V1Pod)
            p.metadata.creation_timestamp = dt.now()
            p.spec.containers = [Mock(name = "analysis")]
            pods.append(p)

        # mock the list namespaced pods with label selector
        reg_k8s_client["list_namespaced_pod_mock"].return_value.items = pods
        response_logs = client.get(
            f'/tasks/{cronjob.id}/logs',
            headers=post_json_admin_header
        )
        assert response_logs.status_code == 200
        assert response_logs.json["logs"] == {
            "pod_0": ['Example logs', 'another line'],
            "pod_1": ['Example logs', 'another line']
        }
