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
        launched = 0
        for project in self.backend_api.get_projects(enabled=True):
            for task in self.backend_api.get_tasks(status=TaskStatus.PENDING.value, project_id=project.id):
                run_request = self._launch(project, task)
                if run_request is None:
                    continue
                yield run_request
                launched += 1

        if not launched:
            yield dg.SkipReason("No pending tasks found.")

    def _launch(self, project: Project, task: Task) -> dg.RunRequest | None:
        """
        The run for the task, or None when its dataset is not active in the project or its secret is
        disabled: the task is failed with the cause recorded, and a manual retry launches it once the dataset is
        active again.
        """
        dataset = None
        if task.spec.dataset_id:
            assignment = self.backend_api.get_project_dataset(project.id, task.spec.dataset_id)
            cause = None
            if not assignment.active:
                cause = f"Dataset {assignment.dataset.name} is not active in project {project.name}"
            elif not assignment.dataset.secret.enabled:
                cause = f"The secret of dataset {assignment.dataset.name} is disabled"
            if cause:
                self.log.warning(f"Task {task.id} not launched: {cause}")
                self.backend_api.patch_task(
                    task.id, {"status": TaskStatus.FAILED.value, "state_cause": cause}
                )
                return None
            dataset = assignment.dataset
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
