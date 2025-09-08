from tests.fixtures.azure_cr_fixtures import *
from tests.fixtures.tasks_fixtures import *


class TestCancelTask:
    def test_cancel_task(
            self,
            client,
            simple_admin_header,
            task
        ):
        """
        Test that an admin can cancel an existing task
        """
        response = client.post(
            f'/tasks/{task.id}/cancel',
            headers=simple_admin_header
        )
        assert response.status_code == 201

    def test_cancel_404_task(
            self,
            client,
            simple_admin_header
        ):
        """
        Test that an admin can cancel a non-existing task returns a 404
        """
        response = client.post(
            '/tasks/123456/cancel',
            headers=simple_admin_header
        )
        assert response.status_code == 404
