from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.registries import RegistryCreate
from app.models.registry import Registry
from app.helpers.container_registries import BaseRegistry
from app.helpers.exceptions import InvalidRequest


class RegistryService:
    @staticmethod
    async def add(session:AsyncSession, data: RegistryCreate) -> Registry:
        q = select(Registry).where(Registry.url == data.url)
        if (await session.execute(q)).one_or_none():
            raise InvalidRequest(f"Registry {data.url} already exist")

        reg_data = data.model_dump()

        reg = Registry(**reg_data)
        _class: BaseRegistry = await reg.get_registry_class()
        await _class.login()
        try:
            await reg.update_regcred()
            await reg.add(session, False)
            await session.commit()
        except:
            await session.rollback()
            raise

        await session.refresh(reg)
        return reg
