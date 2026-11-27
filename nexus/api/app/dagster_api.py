"""
dagster endpoints:
- GET /dagster/sensors
- GET /dagster/sensors/<name>
- PATCH /dagster/sensors
- PATCH /dagster/sensors/<name>
"""
from functools import lru_cache

from fastapi import APIRouter
from fednode.clients.dagster.client import DagsterClient

from app.dtos.sensor import SensorDTO, SensorsStatusRequest, SensorStatusRequest
from app.helpers.const import DAGSTER_WEBSERVER_URI
from app.helpers.exceptions import DBRecordNotFoundError

router = APIRouter(prefix='/dagster', tags=["dagster"])


@lru_cache
def dagster() -> DagsterClient:
    return DagsterClient(DAGSTER_WEBSERVER_URI)


def dto_of(sensors: list[dict]) -> list[SensorDTO]:
    return [SensorDTO.model_validate(s) for s in sensors]


def get_sensor(name: str) -> dict:
    sensor = next((s for s in dagster().list_sensors() if s["name"] == name), None)
    if sensor is None:
        raise DBRecordNotFoundError(f"Sensor {name} not found")
    return sensor


def apply_status(sensors: list[dict], status: str):
    for sensor in sensors:
        if sensor["status"] != status:
            dagster().set_sensor_status(sensor, status)


@router.get('/sensors', response_model=list[SensorDTO])
def get_sensors():
    """
    GET /dagster/sensors — every sensor with its status and latest tick
    """
    return dto_of(dagster().list_sensors())


@router.get('/sensors/{name}', response_model=SensorDTO)
def get_one_sensor(name: str):
    """
    GET /dagster/sensors/<name> — a single sensor
    """
    return dto_of([get_sensor(name)])[0]


@router.patch('/sensors', response_model=list[SensorDTO])
def patch_sensors(req: SensorsStatusRequest):
    """
    PATCH /dagster/sensors — start or stop every sensor, or only those in `names`.
        Unknown names change nothing. Returns every sensor after the change.
    """
    sensors = dagster().list_sensors()
    if req.names is not None:
        unknown = set(req.names) - {s["name"] for s in sensors}
        if unknown:
            raise DBRecordNotFoundError(f"Sensors not found: {', '.join(sorted(unknown))}")
    apply_status([s for s in sensors if req.names is None or s["name"] in req.names], req.status)
    return dto_of(dagster().list_sensors())


@router.patch('/sensors/{name}', response_model=SensorDTO)
def patch_sensor(name: str, req: SensorStatusRequest):
    """
    PATCH /dagster/sensors/<name> — start or stop a single sensor
    """
    apply_status([get_sensor(name)], req.status)
    return dto_of([get_sensor(name)])[0]
