from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.container import Container
from app.schemas.containers import ContainerCreate
from app.models.registry import Registry
from app.helpers.exceptions import ContainerRegistryException, InvalidRequest


class ContainerService:
    @staticmethod
    async def add(session: AsyncSession, data: ContainerCreate, dry_run:bool=False) -> Container:
        container_definition: dict[str, Any] = data.model_dump()

        q = select(Registry).where(Registry.url == data.registry)
        reg: Registry | None = (await session.execute(q)).scalars().one_or_none()
        if reg is None:
            raise ContainerRegistryException(f"Registry {data.registry} could not be found")

        q = select(Container).where(
            Container.name == data.name,
            Registry.id == reg.id
        ).filter(
            (Container.tag==data.tag) & (Container.sha==data.sha)
        ).join(Registry)
        existing_image = (await session.execute(q)).scalars().one_or_none()

        if existing_image:
            raise InvalidRequest(
                f"Image {data.name} with {data.tag or data.sha} already exists in the registry",
                409
            )
        container_definition["registry_id"] = reg.id
        container_definition["registry"] = reg
        container = Container(**container_definition)
        if not dry_run:
          await container.add(session)
        return container
