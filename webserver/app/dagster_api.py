"""
containers endpoints:
- POST /dagster/jobs
"""

from http import HTTPStatus, client
from flask import Blueprint, request
from dagster_graphql import DagsterGraphQLClient, DagsterGraphQLClientError
from dagster import DagsterRunStatus

from app.helpers import exceptions

DAGSTER_WEBSERVER_HOSTNAME = "fn-dev-dagster-webserver"
DAGSTER_REPOSITORY_LOCATION_NAME = "dagster-fn"
DAGSTER_WEBSERVER_PORT = 80
DAGSTER_WEBSERVER_USE_SSL = False
K8S_PIPES_JOB_NAME = "k8s_pipes_job"
K8S_PIPES_OP_NAME = "k8s_pipes_op"


bp = Blueprint("dagster", __name__, url_prefix="/dagster")
dg_client = DagsterGraphQLClient(
    hostname=DAGSTER_WEBSERVER_HOSTNAME,
    port_number=DAGSTER_WEBSERVER_PORT,
    use_https=DAGSTER_WEBSERVER_USE_SSL,
)


@bp.route("/health", methods=["GET"])
def get_health_check():
    """
    GET /dagster/health endpoint.
    """
    return {"status": "ok"}, HTTPStatus.OK


@bp.route("/jobs", methods=["POST"])
def post_job():
    """
    POST /dagster/jobs endpoint.
    """
    data = request.json
    docker_image = data.get("docker_image")

    if not docker_image:
        raise exceptions.InvalidRequest("docker_image required")

    run_id = dg_client.submit_job_execution(
        job_name=K8S_PIPES_JOB_NAME,
        repository_name="__repository__",
        repository_location_name=DAGSTER_REPOSITORY_LOCATION_NAME,
        run_config={
            "ops": {
                K8S_PIPES_OP_NAME: {
                    "config": {
                        "docker_image": docker_image,
                    }
                }
            }
        },
    )

    return {"run_id": run_id}, HTTPStatus.OK


@bp.route("/runs/<string:run_id>", methods=["GET"])
def get_run(run_id: str):
    """
    GET /dagster/runs/<run_id endpoint.
    """
    try:
        status: DagsterRunStatus = dg_client.get_run_status(run_id)
        return {'run_id': run_id, 'status': status.value}, HTTPStatus.OK
    except DagsterGraphQLClientError as exc:
        raise exceptions.LogAndException(f"Error fetching run status: {exc}")
