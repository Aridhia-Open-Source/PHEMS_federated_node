from app.definitions.sensors import git, task

SENSORS = [*git.SENSORS, *task.SENSORS]
JOBS = [*git.JOBS, *task.JOBS]

__all__ = [
    "SENSORS",
    "JOBS",
]
