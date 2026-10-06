"""Dagster GraphQL calls to start, stop and inspect sensors. The webserver needs no auth."""

from fncli.dagster.utils import HttpClient

LOCATION = "dagster-fn"
REPOSITORY = "__repository__"

SELECTOR_VARS = "$selector: SensorSelector!"

START_SENSOR = f"""
mutation StartSensor({SELECTOR_VARS}) {{
  startSensor(sensorSelector: $selector) {{
    __typename
    ... on Sensor {{ sensorState {{ status }} }}
    ... on PythonError {{ message }}
    ... on SensorNotFoundError {{ message }}
    ... on UnauthorizedError {{ message }}
  }}
}}
"""

SENSOR_STATUS = f"""
query SensorStatus({SELECTOR_VARS}) {{
  sensorOrError(sensorSelector: $selector) {{
    __typename
    ... on Sensor {{
      sensorState {{ id status ticks(limit: 3) {{ status skipReason error {{ message }} }} }}
    }}
    ... on PythonError {{ message }}
    ... on SensorNotFoundError {{ message }}
  }}
}}
"""

STOP_SENSOR = """
mutation StopSensor($id: String!) {
  stopSensor(id: $id) {
    __typename
    ... on StopSensorMutationResult { instigationState { status } }
    ... on PythonError { message }
    ... on UnauthorizedError { message }
  }
}
"""

TASK_RUN = """
query TaskRun($filter: RunsFilter!) {
  runsOrError(filter: $filter, limit: 1) {
    __typename
    ... on Runs { results { runId status } }
    ... on PythonError { message }
    ... on InvalidPipelineRunsFilterError { message }
  }
}
"""


class DagsterAPI(HttpClient):
    def graphql(self, query: str, variables: dict) -> dict:
        body = self.post("/graphql", json={"query": query, "variables": variables}).json()
        if body.get("errors"):
            raise RuntimeError(f"Dagster GraphQL error: {body['errors']}")
        return next(iter(body["data"].values()))

    def graphql_ok(self, query: str, variables: dict, result_type: str) -> dict:
        """The result, raising when Dagster answered with an error type instead."""
        result = self.graphql(query, variables)
        if result["__typename"] != result_type:
            raise RuntimeError(f"{result['__typename']}: {result.get('message')}")
        return result

    @staticmethod
    def selector(name: str) -> dict:
        return {
            "selector": {
                "repositoryLocationName": LOCATION,
                "repositoryName": REPOSITORY,
                "sensorName": name,
            }
        }

    def get_sensor_state(self, name: str) -> dict:
        """The sensor's id, status and last 3 ticks."""
        return self.graphql_ok(SENSOR_STATUS, self.selector(name), "Sensor")["sensorState"]

    def start_sensor(self, name: str) -> str:
        """Returns the new status."""
        result = self.graphql_ok(START_SENSOR, self.selector(name), "Sensor")
        return result["sensorState"]["status"]

    def stop_sensor(self, name: str) -> str:
        """Returns the new status."""
        sensor_id = self.get_sensor_state(name)["id"]
        result = self.graphql_ok(
            STOP_SENSOR, {"id": sensor_id}, "StopSensorMutationResult"
        )
        return result["instigationState"]["status"]

    def get_task_run(self, task_id: int) -> dict | None:
        """The task's latest run (runId, status), found by its task_id tag, if it has one."""
        variables = {"filter": {"tags": [{"key": "task_id", "value": str(task_id)}]}}
        results = self.graphql_ok(TASK_RUN, variables, "Runs")["results"]
        return results[0] if results else None
