"""
admin endpoints:
- GET /audit
"""

from http import HTTPStatus
from flask import Blueprint, request
from kubernetes.client.exceptions import ApiException
from sqlalchemy.orm import scoped_session, sessionmaker

from .helpers.base_model import engine
from .helpers.const import (
    TASK_CONTROLLER, CONTROLLER_NAMESPACE, GITHUB_DELIVERY, OTHER_DELIVERY
)
from .helpers.exceptions import FeatureNotAvailableException, InvalidRequest
from .helpers.kubernetes import KubernetesClient
from .helpers.query_filters import parse_query_params
from .helpers.wrappers import audit, auth
from .models.audit import Audit


bp = Blueprint('admin', __name__, url_prefix='/')
session_factory = sessionmaker(bind=engine)
session = scoped_session(session_factory)


@bp.route('/audit', methods=['GET'])
@auth(scope='can_do_admin', check_dataset=False)
def get_audit_logs():
    """
    GET /audit endpoint.
        Returns a list of audit entries
    """
    return parse_query_params(Audit, request.args.copy()), HTTPStatus.OK

@bp.route('/delivery-secret', methods=['PATCH'])
@auth(scope='can_do_admin', check_dataset=False)
@audit
def update_delivery_secret():
    """
    PATCH /delivery-secret
        if the Controller is deployed with the FN
        allows updating the results delivery
        secret
    """
    if not TASK_CONTROLLER:
        raise FeatureNotAvailableException("Task Controller")

    if not request.is_json:
        raise InvalidRequest("Set a json body")

    if not request.json.get("auth"):
        raise InvalidRequest("auth field is mandatory")

    v1_client = KubernetesClient()

    # Which delivery?
    if GITHUB_DELIVERY:
        raise InvalidRequest(
            "Unable to update GitHub delivery details for " \
            "security reasons. Please contact the system administrator"
        )

    try:
        if OTHER_DELIVERY:
            label=f"url={OTHER_DELIVERY}"
            secret = None
            for secret in v1_client.list_namespaced_secret(
                    CONTROLLER_NAMESPACE, label_selector=label
                ).items:
                break

            if secret is None:
                raise InvalidRequest("Could not find a secret to update")

        # Update secret
        secret.data["auth"] = KubernetesClient.encode_secret_value(request.json.get("auth"))
        v1_client.patch_namespaced_secret(
            secret.metadata.name, CONTROLLER_NAMESPACE, secret
        )
    except ApiException as apie:
        raise InvalidRequest(
            "Could not update the secret. Check the logs for more details"
            , 500
        ) from apie

    return "", HTTPStatus.NO_CONTENT
