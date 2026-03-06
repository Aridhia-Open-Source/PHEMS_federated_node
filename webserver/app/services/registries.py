from sqlalchemy import select
from sqlalchemy.orm import Session

from app.schemas.registries import RegistryCreate
from app.models.registry import Registry
from app.helpers.container_registries import BaseRegistry
from app.helpers.exceptions import InvalidRequest


class RegistryService:
    @staticmethod
    def add(session:Session, data: RegistryCreate) -> Registry:
        q = select(Registry).where(Registry.url == data.url)
        if session.execute(q).one_or_none():
            raise InvalidRequest(f"Registry {data.url} already exist")

        reg_data = data.model_dump()

        reg = Registry(**reg_data)
        _class: BaseRegistry = reg.get_registry_class()
        _class.login()
        reg.update_regcred()
        reg.add(session)
        return reg
