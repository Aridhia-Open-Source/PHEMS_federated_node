"""
Client for the Dagster webserver's GraphQL API, used to read and toggle sensors.
"""
from datetime import datetime, timezone

import requests

from app.helpers.const import DAGSTER_WEBSERVER_URI
from app.helpers.exceptions import DagsterError

SENSORS_QUERY = """
query Sensors {
  repositoriesOrError {
    __typename
    ... on RepositoryConnection {
      nodes {
        name
        location { name }
        sensors {
          name
          sensorState {
            id
            status
            ticks(limit: 1) { timestamp status }
          }
        }
      }
    }
    ... on PythonError { message }
  }
}
"""

START_SENSOR_MUTATION = """
mutation StartSensor($selector: SensorSelector!) {
  startSensor(sensorSelector: $selector) {
    __typename
    ... on PythonError { message }
    ... on SensorNotFoundError { message }
    ... on UnauthorizedError { message }
  }
}
"""

STOP_SENSOR_MUTATION = """
mutation StopSensor($id: String!) {
  stopSensor(id: $id) {
    __typename
    ... on PythonError { message }
    ... on UnauthorizedError { message }
  }
}
"""

ERROR_TYPES = ("PythonError", "SensorNotFoundError", "UnauthorizedError")


def graphql(query: str, variables: dict | None = None) -> dict:
    """Run a query against Dagster, returning its data. Anything but data is a DagsterError."""
    try:
        response = requests.post(
            f"{DAGSTER_WEBSERVER_URI}/graphql",
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
    except (requests.exceptions.RequestException, ValueError) as err:
        raise DagsterError(f"Dagster is unreachable: {err}") from err
    if body.get("errors"):
        raise DagsterError(f"Dagster GraphQL error: {body['errors'][0]['message']}")
    return body["data"]


def check_result(result: dict):
    if result["__typename"] in ERROR_TYPES:
        raise DagsterError(f"Dagster error: {result['message']}")


def list_sensors() -> list[dict]:
    """
    Every sensor with its status and latest tick, plus the ids needed to change it.
    """
    result = graphql(SENSORS_QUERY)["repositoriesOrError"]
    check_result(result)
    sensors = []
    for repository in result["nodes"]:
        for sensor in repository["sensors"]:
            state = sensor["sensorState"]
            tick = state["ticks"][0] if state["ticks"] else None
            sensors.append({
                "name": sensor["name"],
                "status": state["status"],
                "last_tick": (
                    datetime.fromtimestamp(tick["timestamp"], timezone.utc).isoformat()
                    if tick else None
                ),
                "error": bool(tick) and tick["status"] == "FAILURE",
                "state_id": state["id"],
                "selector": {
                    "repositoryLocationName": repository["location"]["name"],
                    "repositoryName": repository["name"],
                    "sensorName": sensor["name"],
                },
            })
    return sensors


def set_sensor_status(sensor: dict, status: str):
    """Start or stop one sensor, as returned by list_sensors."""
    if status == "RUNNING":
        result = graphql(START_SENSOR_MUTATION, {"selector": sensor["selector"]})["startSensor"]
    else:
        result = graphql(STOP_SENSOR_MUTATION, {"id": sensor["state_id"]})["stopSensor"]
    check_result(result)
