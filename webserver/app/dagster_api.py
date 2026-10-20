"""
dagster endpoints:
- GET /dagster/sensors
- GET /dagster/sensors/<name>
- PATCH /dagster/sensors
- PATCH /dagster/sensors/<name>
"""
from http import HTTPStatus

from flask import Blueprint, request

from app.dtos.sensor import SensorDTO
from app.helpers.dagster import list_sensors, set_sensor_status
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.wrappers import audit, auth

bp = Blueprint('dagster', __name__, url_prefix='/dagster')

STATUSES = ("RUNNING", "STOPPED")


@bp.before_request
@auth(scope='can_do_admin')
def auth_before():
    """Ensure the user is an admin."""


def dump(sensors: list[dict]) -> list[dict]:
    return [SensorDTO.model_validate(s).dump() for s in sensors]


def get_sensor(name: str) -> dict:
    sensor = next((s for s in list_sensors() if s["name"] == name), None)
    if sensor is None:
        raise DBRecordNotFoundError(f"Sensor {name} not found")
    return sensor


def requested_status() -> str:
    body = request.get_json()
    status = body.get("status") if isinstance(body, dict) else None
    if status not in STATUSES:
        raise InvalidRequest(f"status must be one of {', '.join(STATUSES)}")
    return status


def apply_status(sensors: list[dict], status: str):
    for sensor in sensors:
        if sensor["status"] != status:
            set_sensor_status(sensor, status)


@bp.route('/sensors', methods=['GET'])
def get_sensors():
    """
    GET /dagster/sensors — every sensor with its status and latest tick
    """
    return dump(list_sensors()), HTTPStatus.OK


@bp.route('/sensors/<name>', methods=['GET'])
def get_one_sensor(name):
    """
    GET /dagster/sensors/<name> — a single sensor
    """
    return dump([get_sensor(name)])[0], HTTPStatus.OK


@bp.route('/sensors', methods=['PATCH'])
@audit
def patch_sensors():
    """
    PATCH /dagster/sensors — start or stop every sensor, or only those in `names`.
        Unknown names change nothing. Returns every sensor after the change.
    """
    status = requested_status()
    names = request.get_json().get("names")
    if names is not None and not (isinstance(names, list) and all(isinstance(n, str) for n in names)):
        raise InvalidRequest("names must be a list of sensor names")

    sensors = list_sensors()
    if names is not None:
        unknown = set(names) - {s["name"] for s in sensors}
        if unknown:
            raise DBRecordNotFoundError(f"Sensors not found: {', '.join(sorted(unknown))}")
    apply_status([s for s in sensors if names is None or s["name"] in names], status)
    return dump(list_sensors()), HTTPStatus.OK


@bp.route('/sensors/<name>', methods=['PATCH'])
@audit
def patch_sensor(name):
    """
    PATCH /dagster/sensors/<name> — start or stop a single sensor
    """
    status = requested_status()
    apply_status([get_sensor(name)], status)
    return dump([get_sensor(name)])[0], HTTPStatus.OK
