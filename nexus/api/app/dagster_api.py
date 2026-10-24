"""
dagster endpoints:
- GET /dagster/sensors
- GET /dagster/sensors/<name>
- PATCH /dagster/sensors
- PATCH /dagster/sensors/<name>
"""
from fastapi import APIRouter, Body, Depends

from app.dtos.sensor import SensorDTO
from app.helpers.dagster import list_sensors, set_sensor_status
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.wrappers import require_scope

router = APIRouter(prefix='/dagster', tags=["dagster"], dependencies=[Depends(require_scope('can_do_admin'))])

STATUSES = ("RUNNING", "STOPPED")


def dto_of(sensors: list[dict]) -> list[SensorDTO]:
    return [SensorDTO.model_validate(s) for s in sensors]


def get_sensor(name: str) -> dict:
    sensor = next((s for s in list_sensors() if s["name"] == name), None)
    if sensor is None:
        raise DBRecordNotFoundError(f"Sensor {name} not found")
    return sensor


def requested_status(body: dict) -> str:
    status = body.get("status")
    if status not in STATUSES:
        raise InvalidRequest(f"status must be one of {', '.join(STATUSES)}")
    return status


def apply_status(sensors: list[dict], status: str):
    for sensor in sensors:
        if sensor["status"] != status:
            set_sensor_status(sensor, status)


@router.get('/sensors', response_model=list[SensorDTO])
def get_sensors():
    """
    GET /dagster/sensors — every sensor with its status and latest tick
    """
    return dto_of(list_sensors())


@router.get('/sensors/{name}', response_model=SensorDTO)
def get_one_sensor(name: str):
    """
    GET /dagster/sensors/<name> — a single sensor
    """
    return dto_of([get_sensor(name)])[0]


@router.patch('/sensors', response_model=list[SensorDTO])
def patch_sensors(body: dict = Body(default_factory=dict)):
    """
    PATCH /dagster/sensors — start or stop every sensor, or only those in `names`.
        Unknown names change nothing. Returns every sensor after the change.
    """
    status = requested_status(body)
    names = body.get("names")
    if names is not None and not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
        raise InvalidRequest("names must be a list of sensor names")

    sensors = list_sensors()
    if names is not None:
        unknown = set(names) - {s["name"] for s in sensors}
        if unknown:
            raise DBRecordNotFoundError(f"Sensors not found: {', '.join(sorted(unknown))}")
    apply_status([s for s in sensors if names is None or s["name"] in names], status)
    return dto_of(list_sensors())


@router.patch('/sensors/{name}', response_model=SensorDTO)
def patch_sensor(name: str, body: dict = Body(default_factory=dict)):
    """
    PATCH /dagster/sensors/<name> — start or stop a single sensor
    """
    status = requested_status(body)
    apply_status([get_sensor(name)], status)
    return dto_of([get_sensor(name)])[0]
