"""
Running health checks: whatever reads the database or the cluster happens in the request (the prepare_*
functions in this package), and only the network calls run in threads, here.
"""
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app.dtos.project import HealthCheckDTO
from app.models.git_provider import ConnectionCheck, ConnectionStatus

HEALTHCHECK_MAX_WORKERS = 8


def health_check_dto(check: ConnectionCheck) -> HealthCheckDTO:
    return HealthCheckDTO(message=check.message, status_code=check.status_code, latency_ms=check.latency_ms)

def run_all(checks: list[Callable]) -> list:
    with ThreadPoolExecutor(max_workers=HEALTHCHECK_MAX_WORKERS) as executor:
        return list(executor.map(lambda check: check(), checks))

def is_ok(items) -> bool:
    return all(item.status == ConnectionStatus.OK for item in items)
