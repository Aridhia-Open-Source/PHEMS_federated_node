"""
admin endpoints:
- GET /audit
"""

from http import HTTPStatus
from typing import Annotated, Any
from fastapi import APIRouter, Depends, Query, Request
from kubernetes_asyncio.client.exceptions import ApiException
from kubernetes_asyncio.client.models.v1_secret_list import V1SecretList
from sqlalchemy.ext.asyncio import AsyncSession

from ..helpers.base_model import get_db
from ..helpers.exceptions import FeatureNotAvailableException, InvalidRequest
from ..helpers.kubernetes import KubernetesClient
from ..helpers.settings import settings
from ..helpers.query_filters import apply_filters
from ..helpers.wrappers import audit, Auth
from ..models.audit import Audit
from ..schemas.audits import AuditBase, AuditFilters
from ..schemas.delivery_secrets import DeliverySecretPost
from ..schemas.pagination import PageResponse


router = APIRouter(tags=["admin"])


@router.get('/audit', dependencies=[Depends(Auth("can_do_admin"))])
async def get_audit_logs(
    params: Annotated[AuditFilters, Query()],
    session: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """
    GET /audit endpoint.
        Returns a list of audit entries
    """
    pagination = await apply_filters(session, Audit, params)
    return PageResponse[AuditBase].model_validate(pagination).model_dump()


@router.patch(
    '/delivery-secret',
    status_code=HTTPStatus.NO_CONTENT,
    dependencies=[Depends(Auth("can_do_admin"))]
)
@audit
async def update_delivery_secret(
    request: Request,
    body: DeliverySecretPost,
    session: AsyncSession = Depends(get_db)
) -> None:
    """
    PATCH /delivery-secret
        if the Controller is deployed with the FN
        allows updating the results delivery
        secret
    """
    if not settings.task_controller:
        raise FeatureNotAvailableException("Task Controller")

    v1_client: KubernetesClient = await KubernetesClient.create()

    # Which delivery?
    if settings.github_delivery:
        raise InvalidRequest(
            "Unable to update GitHub delivery details for " \
            "security reasons. Please contact the system administrator"
        )

    try:
        if settings.other_delivery:
            label=f"url={settings.other_delivery}"
            secret = None
            sec_list: V1SecretList = await v1_client.api_client.list_namespaced_secret(
                settings.controller_namespace, label_selector=label
            )
            for secret in sec_list.items:
                break

            if secret is None:
                raise InvalidRequest("Could not find a secret to update")

        # Update secret
        secret.data["auth"] = KubernetesClient.encode_secret_value(body.auth)
        await v1_client.api_client.patch_namespaced_secret(
            secret.metadata.name, settings.controller_namespace, secret
        )
    except ApiException as apie:
        raise InvalidRequest(
            "Could not update the secret. Check the logs for more details"
            , 500
        ) from apie
