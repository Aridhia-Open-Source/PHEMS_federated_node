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
from sqlalchemy.orm import Session as DBSession

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
    session: Session = Depends(get_db)
) -> dict[str, Any]:
    """
    GET /registries endpoint.
    """
    pagination = await apply_filters(session, Registry, params)
    return PageResponse[RegistryRead].model_validate(pagination).model_dump()


@router.get('/{registry_id}', dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def registry_by_id(
    registry_id:int,
    request: Request,
    session: DBSession = Depends(get_db)
) -> dict[str, Any]:
    """
    GET /registries endpoint.
    """
    registry = await Registry.get_by_id(session, registry_id)
    if registry is None:
        raise DBRecordNotFoundError("Registry not found")

    return RegistryRead.model_validate(registry).model_dump()


@router.delete('/{registry_id}', status_code=HTTPStatus.NO_CONTENT, dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def delete_registry_by_id(
    registry_id:int,
    request: Request,
    session: DBSession = Depends(get_db)
) -> None:
    """
    GET /registries endpoint.
    """
    registry: Registry = await Registry.get_by_id(session, registry_id)
    if registry is None:
        raise DBRecordNotFoundError("Registry not found")

    await registry.delete(session)


@router.post('', status_code=HTTPStatus.CREATED, dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def add_registry(
    request: Request,
    body: RegistryCreate,
    session: DBSession = Depends(get_db)
) -> dict[str, Any]:
    """
    POST /registries endpoint.
    """
    registry: Registry = await RegistryService.add(session, body)
    return RegistryRead.model_validate(registry).model_dump()


@router.patch('/{registry_id}', status_code=HTTPStatus.NO_CONTENT, dependencies=[Depends(Auth("can_admin_dataset"))])
@audit
async def patch_registry(
    registry_id:int,
    body: RegistryUpdate,
    request:Request,
    session: DBSession = Depends(get_db)
) -> None:
    """
    PATCH /registries/<registry_id> endpoint.
    """
    registry: Registry = await Registry.get_by_id(session, registry_id)
    if registry is None:
        raise InvalidRequest(f"Registry {registry_id} not found")

    if not body.model_dump(exclude_unset=True):
        raise InvalidRequest("No valid changes detected")

    await RegistryService.update(session, registry, body)
