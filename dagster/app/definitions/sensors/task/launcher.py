import dagster as dg

from app.backend import BackendAPI
from app.definitions.run_config import build_run_config
from app.definitions.sensors.base import BaseSensor
from app.models import Project, Task, TaskStatus


class TaskLauncherSensor(BaseSensor):
    """Launches a run for each PENDING task of an enabled project."""

    def __init__(self, context, backend_api: BackendAPI):
        super().__init__(context)
        self.backend_api = backend_api

    def __call__(self):
        """
        Execute the sensor. Yields a RunRequest per PENDING task, or a SkipReason.

        The launcher patches nothing: the run-status sensors move the task on once Dagster
        has the run, and the run key (task id and attempt) de-duplicates the re-yield until
        then. A retry bumps the attempt, so it gets a new run key.
        """
        projects = [p for p in self.backend_api.get_projects() if p.enabled]
        launched = 0
        for project in projects:
            for task in self.backend_api.get_tasks(status=TaskStatus.PENDING.value, project_id=project.id):
                yield self._launch(project, task)
                launched += 1

        if not launched:
            yield dg.SkipReason("No pending tasks found.")

    def _launch(self, project: Project, task: Task) -> dg.RunRequest:
        dataset = self.backend_api.get_dataset(task.dataset_id)
        return dg.RunRequest(
            run_key=f"task/{task.id}/{task.attempt}",
            tags={
                "trigger": "task",
                "task_id": str(task.id),
                "attempt": str(task.attempt),
                "project_id": str(project.id),
                "project": project.name,
            },
            run_config=build_run_config(task.spec, dataset),
        )
