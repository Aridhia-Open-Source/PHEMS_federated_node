"""
containers endpoints:
- GET /containers
- POST /containers
- GET /containers/<id>
- PATCH /containers/<id>
- POST /registries
"""
import logging
from http import HTTPStatus
from typing import Annotated, Any
from fastapi import APIRouter, Depends, Query, Request
from requests import Session
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from app.helpers.base_model import get_db
from app.helpers.exceptions import InvalidRequest, DBRecordNotFoundError
from app.helpers.query_filters import apply_filters
from app.helpers.wrappers import Auth, audit

from app.models.container import Container
from app.models.registry import Registry

from app.schemas.containers import ContainerCreate, ContainerRead, ContainerFilters, ContainerUpdate
from app.schemas.pagination import PageResponse
from app.services.containers import ContainerService


logger = logging.getLogger('containers_api')
logger.setLevel(logging.INFO)

router = APIRouter(tags=["containers"], prefix="/containers")


@router.get('', dependencies=[Depends(Auth("can_do_admin"))])
@audit
async def get_all_containers(
    request: Request,
    params: Annotated[ContainerFilters, Query()],
    session: Session = Depends(get_db)
) -> dict[str, Any]:
    """
    GET /containers endpoint.
        Returns the list of allowed containers
    """
    pagination = await apply_filters(session, Container, params)
    return PageResponse[ContainerRead].model_validate(pagination).model_dump()


@router.post('',
             dependencies=[Depends(Auth("can_do_admin"))],
             status_code=HTTPStatus.CREATED
             )
@audit
async def add_image(
    request: Request,
    body: ContainerCreate,
    session: DBSession = Depends(get_db)
) -> dict[str, Any]:
    """
    POST /containers endpoint.
    """
    # Make sure it doesn't exist already
    image: Container = await ContainerService.add(session, data=body)
    return ContainerRead.model_validate(image).model_dump()


@router.get('/{image_id}', dependencies=[Depends(Auth("can_do_admin"))])
@audit
async def get_image_by_id(
    request:Request,
    image_id:int,
    session: DBSession = Depends(get_db)
) -> dict[str, Any]:
    """
    GET /containers/<image_id>
    """
    image: Container = await Container.get_by_id(session, image_id)
    if not image:
        raise DBRecordNotFoundError(f"Container with id {image_id} does not exist")

    return ContainerRead.model_validate(image).model_dump()


@router.patch('/{image_id}',
              dependencies=[Depends(Auth("can_do_admin"))],
              status_code=HTTPStatus.CREATED
            )
@audit
async def patch_containers_by_id_or_name(
    request:Request,
    image_id:int,
    body: ContainerUpdate,
    session: DBSession = Depends(get_db)
):
    """
    PATCH /containers/id endpoint. Edits an existing container image with a given id
    """
    container = await Container.get_by_id(session, image_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise InvalidRequest("No valid changes detected")

    await container.update(session, changes)


@router.post('/sync',
             dependencies=[Depends(Auth("can_do_admin"))],
             status_code=HTTPStatus.CREATED
             )
@audit
async def sync(request:Request, session: DBSession = Depends(get_db)) -> dict[str, Any]:
    """
    POST /containers/sync
        syncs up the list of available containers from the
        available registries and adds them to the DB table
        with both dashboard and ml flags to false, effectively
        making them not usable. To "enable" them one of those
        flags has to set to true. This is done to avoid undesirable
        or unintended containers to be used on a node.
    """
    synched: list[Container] = []
    registry_query = await session.execute(select(Registry).where(Registry.active == True))
    for registry in registry_query.scalars().all():
        for image in registry.fetch_image_list():
            for key in ["tag", "sha"]:
                for tag_or_sha in image[key]:
                    images_query = await session.execute(select(Container).where(
                        Container.name==image["name"],
                        getattr(Container, key)==tag_or_sha,
                        Container.registry_id==registry.id
                    ))
                    if images_query.scalars().one_or_none():
                        logger.info("Image %s already synched", image["name"])
                        continue

                    container_data = {
                        "name": image["name"],
                        "registry": registry.url
                    }
                    if key == "tag":
                        container_data["tag"] = tag_or_sha
                    else:
                        container_data["sha"] = tag_or_sha

                    cont: Container = await ContainerService.add(session, ContainerCreate(**container_data), dry_run=True)

                    synched.append(cont)

    session.add_all(synched)
    await session.commit()
    return {
        "info": "The sync considers only the latest 100 tag per image. If an older one is needed,"
                " add it manually via the POST /images endpoint",
        "images": [syn.full_image_name() for syn in synched]
    }
