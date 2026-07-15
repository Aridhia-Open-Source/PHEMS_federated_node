from app.definitions.sensors import github


SENSORS = [
    *github.SENSORS
]

JOBS = [
    *github.JOBS
]

__all__ = [
    "SENSORS",
    "JOBS",
]
