import dagster as dg

from app.backend import BackendAPI
from app.definitions.run_config import build_run_config
from app.definitions.sensors.base import BaseSensor
from app.models import Project, Task, TaskConfig, TaskStatus

MAX_CAUSE_LENGTH = 1024


class TaskLauncherSensor(BaseSensor):
    """Launches a run for each PENDING task of an enabled project, as the backend decides."""

    def __init__(self, context, backend_api: BackendAPI):
        super().__init__(context)
        self.backend_api = backend_api

    def __call__(self):
        """
        Execute the sensor. Yields a RunRequest per PENDING task, or a SkipReason.

        The launcher patches nothing: the run-status sensors move the task on once Dagster
        has the run, and the run key (task id and attempt) de-duplicates the re-yield until
        then. A retry bumps the attempt, so it gets a new run key.

        Only the backend's decision fails a task (see _launch). An error while asking for it, e.g. the config GET
        failing, is logged and the task stays PENDING for the next tick: no run was created, so its
        run key is unused. One bad task must not stop the others from launching.
        """
        launched = 0
        for project in self.backend_api.get_projects(enabled=True):
            for task in self.backend_api.get_tasks(status=TaskStatus.PENDING.value, project_id=project.id):
                try:
                    run_request = self._launch(project, task)
                except Exception as e:
                    self.log.exception(f"Task {task.id} not launched, retried on the next tick: {e!r}")
                    continue
                if run_request is None:
                    continue
                yield run_request
                launched += 1

        if not launched:
            yield dg.SkipReason("No pending tasks found.")

    def _fail(self, project: Project, task: Task, cause: str) -> None:
        """Records the cause on the task and fails it, so it does not launch."""
        self.log.warning(f"Task {task.id} not launched: {cause}")
        self.backend_api.patch_task(
            project.id, task.id,
            {"status": TaskStatus.FAILED.value, "state_cause": cause[:MAX_CAUSE_LENGTH]},
        )

    def _launch(self, project: Project, task: Task) -> dg.RunRequest | None:
        """
        Asks the backend what to do with the task and does it: on "fail" it records the cause and returns None,
        on "launch" it returns the run. The rules are the backend's (see its decide_launch); none are checked here.
        A manual retry launches a failed task once the cause is gone. Any error is raised.
        """
        decision = TaskConfig.model_validate(self.backend_api.get_task_config(project.id, task.id))
        if decision.outcome == "fail":
            self._fail(project, task, decision.cause or "failed by the backend")
            return None
        # The run config needs the dataset's connection details, not a decision about it
        dataset = None
        if task.spec.dataset_id:
            dataset = self.backend_api.get_project_dataset(project.id, task.spec.dataset_id).dataset
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
