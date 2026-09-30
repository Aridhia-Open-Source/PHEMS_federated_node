from app.definitions.sensors import git, gitea, github

SENSORS = [*git.SENSORS, *gitea.SENSORS, *github.SENSORS]
JOBS = [*git.JOBS, *gitea.JOBS, *github.JOBS]

__all__ = [
    "SENSORS",
    "JOBS",
]
