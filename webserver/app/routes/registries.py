"""
containers endpoints:
- GET /registries
- GET /registries/<registry_id>
- POST /registries
- PATCH /registries/<registry_id>
"""

from http import HTTPStatus
from typing import Annotated, Any
from fastapi import APIRouter, Depends, Query, Request
from requests import Session

from app.helpers.base_model import get_db
from app.helpers.exceptions import DBRecordNotFoundError, InvalidRequest
from app.helpers.query_filters import apply_filters
from app.helpers.wrappers import Auth, audit

from app.models.registry import Registry

from app.schemas.pagination import PageResponse
from app.schemas.registries import RegistryCreate, RegistryFilters, RegistryRead, RegistryUpdate
from app.services.registries import RegistryService


router = APIRouter(tags=["registries"], prefix="/registries")


@router.get('', dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def list_registries(
    params: Annotated[RegistryFilters, Query()],
    request: Request,
    db: Session = Depends(get_db)
) -> dict[str, Any]:
    """
    GET /registries endpoint.
    """

    pagination = apply_filters(db, Registry, params)
    return PageResponse[RegistryRead].model_validate(pagination).model_dump()


@router.get('/{registry_id}', dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def registry_by_id(
    registry_id:int,
    request: Request
) -> dict[str, Any]:
    """
    GET /registries endpoint.
    """
    registry = Registry.get_by_id(registry_id)
    if registry is None:
        raise DBRecordNotFoundError("Registry not found")

    return RegistryRead.model_validate(registry).model_dump()


@router.delete('/{registry_id}', status_code=HTTPStatus.NO_CONTENT, dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def delete_registry_by_id(registry_id:int, request: Request) -> None:
    """
    GET /registries endpoint.
    """
    registry = Registry.get_by_id(registry_id)
    if registry is None:
        raise DBRecordNotFoundError("Registry not found")

    with get_db() as session:
        registry.delete(session, commit=True)


@router.post('', status_code=HTTPStatus.CREATED, dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def add_registry(
    request: Request,
    body: RegistryCreate
):
    """
    POST /registries endpoint.
    """
    registry = RegistryService.add(body)
    return RegistryRead.model_validate(registry).model_dump()


@router.patch('/{registry_id}', status_code=HTTPStatus.NO_CONTENT, dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def patch_registry(registry_id:int, body: RegistryUpdate, request:Request) -> None:
    """
    PATCH /registries/<registry_id> endpoint.
    """
    registry = Registry.get_by_id(registry_id)
    if registry is None:
        raise InvalidRequest(f"Registry {registry_id} not found")

    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise InvalidRequest("No valid changes detected")

    Registry.update(registry_id, changes)
