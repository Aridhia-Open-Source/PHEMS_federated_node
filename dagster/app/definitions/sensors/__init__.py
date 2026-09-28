import os

GIT_PROVIDER = os.getenv("GIT_PROVIDER", "github").lower()

if GIT_PROVIDER == "gitea":
    from app.definitions.sensors import gitea
    SENSORS = [*gitea.SENSORS]
    JOBS = [*gitea.JOBS]
else:
    from app.definitions.sensors import github
    SENSORS = [*github.SENSORS]
    JOBS = [*github.JOBS]

__all__ = [
    "SENSORS",
    "JOBS",
]
