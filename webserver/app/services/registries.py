from app.schemas.registries import RegistryCreate
from app.models.registry import Registry
from app.helpers.container_registries import BaseRegistry
from app.helpers.base_model import get_db


class RegistryService:
    @staticmethod
    def add(data: RegistryCreate) -> Registry:
        reg_data = data.model_dump()
        reg = Registry(**reg_data)
        _class: BaseRegistry = reg.get_registry_class()
        _class.login()
        reg.update_regcred()
        with get_db() as session:
            reg.add(session)
        return reg
