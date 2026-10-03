from app.definitions.sensors import git, github, task

SENSORS = [*git.SENSORS, *github.SENSORS, *task.SENSORS]
JOBS = [*git.JOBS, *github.JOBS, *task.JOBS]

__all__ = [
    "SENSORS",
    "JOBS",
]
