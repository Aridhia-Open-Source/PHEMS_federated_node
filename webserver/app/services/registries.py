from app.schemas.registries import RegistryCreate
from app.models.registry import Registry
from app.helpers.container_registries import BaseRegistry


class RegistryService:
    @staticmethod
    def add(data: RegistryCreate):
        reg_data = data.model_dump()
        user = reg_data.pop("username")
        passw = reg_data.pop("password")
        reg = Registry(**reg_data)
        _class: BaseRegistry = reg.get_registry_class()
        _class.login()
        reg.update_regcred(user, passw)
        reg.add()
