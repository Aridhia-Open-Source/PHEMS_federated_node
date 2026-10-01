import dagster as dg

from app.backend import BackendAPI
from app.definitions.run_config import build_run_config
from app.definitions.sensors.base import BaseSensor
from app.models import Project, TaskRequest


class TaskRequestLauncherSensor(BaseSensor):
    """Launches a run for each queued task request of an enabled project."""

    def __init__(self, context, backend_api: BackendAPI):
        super().__init__(context)
        self.backend_api = backend_api

    def __call__(self):
        """
        Execute the sensor. Yields a RunRequest per queued task request, or a SkipReason.

        Flow:
        1. Fetch the enabled projects
        2. For each, fetch its queued task requests
        3. Ensure the task exists, build the run config for its dataset and yield the run

        The launcher marks nothing: code after a yield still runs before Dagster creates
        the run, so the request stays queued and its run key de-duplicates the re-yield
        until the run-status sensors see the run start.
        """
        projects = [p for p in self.backend_api.get_projects() if p.enabled]
        launched = 0
        for project in projects:
            try:
                task_requests = self.backend_api.get_task_requests(queued=True, project_id=project.id)
            except Exception as e:
                self.log.error(f"Failed to fetch task requests for project {project.id}: {e}")
                continue

            for task_request in task_requests:
                try:
                    yield self._launch(project, task_request)
                    launched += 1
                except Exception as e:
                    self.log.error(f"Failed to launch task request {task_request.id}: {e}")

        if not launched:
            yield dg.SkipReason("No queued task requests found.")

    def _launch(self, project: Project, task_request: TaskRequest) -> dg.RunRequest:
        task = self.backend_api.create_task(task_request.id)
        dataset = self.backend_api.get_dataset(task.dataset_id)
        run_config = build_run_config(task_request.payload, dataset)
        return dg.RunRequest(
            run_key=f"task_request/{task_request.id}",
            tags={
                "trigger": "task_request",
                "task_request_id": str(task_request.id),
                "task_id": str(task.id),
                "project_id": str(project.id),
                "project": project.name,
            },
            run_config=run_config,
        )
