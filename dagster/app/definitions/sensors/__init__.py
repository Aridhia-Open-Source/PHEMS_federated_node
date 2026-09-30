from app.definitions.sensors import git, gitea, github, task_request

SENSORS = [*git.SENSORS, *gitea.SENSORS, *github.SENSORS, *task_request.SENSORS]
JOBS = [*git.JOBS, *gitea.JOBS, *github.JOBS, *task_request.JOBS]

__all__ = [
    "SENSORS",
    "JOBS",
]
