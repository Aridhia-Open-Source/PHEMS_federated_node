import dagster as dg

from app.backend import BackendAPI
from app.definitions.run_config import build_run_config
from app.definitions.sensors.base import BaseSensor
from app.models import Project, Task, TaskStatus


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

        Only the backend's decision fails a task, and it does so itself (see _launch). An error while asking for it, e.g. the launch call
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

    def _launch(self, project: Project, task: Task) -> dg.RunRequest | None:
        """
        Asks the backend to launch the task, one call. On "launch" it returns the run, built from the task and dataset
        the backend sends. On "fail" the backend has already moved the task to FAILED with the cause, so it returns
        None, as it does for a task that is no longer PENDING. The rules are the backend's (see its decide_launch);
        none are checked here. A manual retry launches a failed task once the cause is gone. Any error is raised.
        """
        decision = self.backend_api.launch_task(project.id, task.id)
        if decision is None:
            self.log.info(f"Task {task.id} is no longer pending, skipped")
            return None
        if decision.outcome == "fail":
            self.log.warning(f"Task {task.id} not launched: {decision.cause}")
            return None
        return dg.RunRequest(
            run_key=f"task/{decision.task.id}/{decision.task.attempt}",
            tags={
                "trigger": "task",
                "task_id": str(decision.task.id),
                "attempt": str(decision.task.attempt),
                "project_id": str(project.id),
                "project": project.name,
            },
            run_config=build_run_config(decision.task.spec, decision.dataset),
        )
