"""
containers endpoints:
- POST /dagster/jobs
"""

from http import HTTPStatus, client
from flask import Blueprint, request
from dagster_graphql import DagsterGraphQLClient

DAGSTER_WEBSERVER_HOSTNAME = "fn-dev-dagster-webserver"
DAGSTER_REPOSITORY_LOCATION_NAME = "dagster-fn"
DAGSTER_WEBSERVER_PORT = 80
DAGSTER_WEBSERVER_USE_SSL = False
K8S_PIPES_JOB_NAME = 'k8s_pipes_job'
K8S_PIPES_OP_NAME = 'k8s_pipes_op'


bp = Blueprint('dagster', __name__, url_prefix='/dagster')
dg_client = DagsterGraphQLClient(
    hostname=DAGSTER_WEBSERVER_HOSTNAME,
    port=DAGSTER_WEBSERVER_PORT,
    use_ssl=DAGSTER_WEBSERVER_USE_SSL
)


@bp.route('/jobs', methods=['POST'])
def post_job():
    """
    POST /jobs endpoint.
    """
    data = request.json
    docker_image = data["docker_image"]

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
