"""
admin endpoints:
- GET /audit
"""

from http import HTTPStatus
from typing import Annotated, Any
from fastapi import APIRouter, Depends, Query, Request
from kubernetes.client.exceptions import ApiException
from requests import Session

from app.helpers.base_model import get_db
from app.helpers.const import (
    TASK_CONTROLLER, CONTROLLER_NAMESPACE,
    GITHUB_DELIVERY, OTHER_DELIVERY
)
from app.helpers.exceptions import FeatureNotAvailableException, InvalidRequest
from app.helpers.kubernetes import KubernetesClient
from app.helpers.query_filters import apply_filters
from app.helpers.wrappers import audit, Auth
from app.models.audit import Audit
from app.schemas.audits import AuditBase, AuditFilters
from app.schemas.pagination import PageResponse
from app.schemas.delivery_secrets import DeliverySecretPost


router = APIRouter(tags=["admin"])


@router.get('/audit', dependencies=[Depends(Auth("can_do_admin"))])
async def get_audit_logs(
    params: Annotated[AuditFilters, Query()],
    db: Session = Depends(get_db)
) -> dict[str, Any]:
    """
    GET /audit endpoint.
        Returns a list of audit entries
    """
    pagination = apply_filters(db, Audit, params)
    return PageResponse[AuditBase].model_validate(pagination).model_dump()


@router.patch(
    '/delivery-secret',
    status_code=HTTPStatus.NO_CONTENT,
    dependencies=[Depends(Auth("can_do_admin"))]
)
@audit
async def update_delivery_secret(request: Request, body: DeliverySecretPost) -> None:
    """
    PATCH /delivery-secret
        if the Controller is deployed with the FN
        allows updating the results delivery
        secret
    """
    if not TASK_CONTROLLER:
        raise FeatureNotAvailableException("Task Controller")

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
        secret.data["auth"] = KubernetesClient.encode_secret_value(body.auth)
        v1_client.patch_namespaced_secret(
            secret.metadata.name, CONTROLLER_NAMESPACE, secret
        )
    except ApiException as apie:
        raise InvalidRequest(
            "Could not update the secret. Check the logs for more details"
            , 500
        ) from apie
