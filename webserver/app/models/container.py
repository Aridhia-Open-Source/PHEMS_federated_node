import re
from sqlalchemy import Column, Integer, Boolean, String, ForeignKey
from sqlalchemy.orm import relationship
from app.helpers.base_model import BaseModel, db
from app.models.registry import Registry
from app.helpers.exceptions import ContainerRegistryException, InvalidRequest


class Container(db.Model, BaseModel):
    __tablename__ = 'containers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    tag = Column(String(256), nullable=False)
    ml = Column(Boolean(), default=False)
    dashboard = Column(Boolean(), default=False)

    registry_id = Column(Integer, ForeignKey(Registry.id, ondelete='CASCADE'))
    registry = relationship("Registry")

    def __init__(
            self,
            name:str,
            registry:Registry,
            tag:str,
            ml:bool=False,
            dashboard:bool=False
        ):
        self.name = name
        self.registry = registry
        self.tag = tag
        self.ml = ml
        self.dashboard = dashboard

        # Check if the image is there

    @classmethod
    def validate(cls, data:dict):
        data = super().validate(data)

        reg = Registry.query.filter(Registry.url==data["registry"]).one_or_none()
        if reg is None:
            raise ContainerRegistryException(f"Registry {data["registry"]} could not be found")
        data["registry"] = reg

        img_with_tag = f"{data["name"]}:{data["tag"]}"
        if not re.match(r'^((\w+|-|\.)\/?+)+:(\w+(\.|-)?)+$', img_with_tag):
            raise InvalidRequest(
                f"{img_with_tag} does not have a tag. Please provide one in the format <image>:<tag>"
            )
        return data

    def full_image_name(self):
        return f"{self.registry.url}/{self.name}:{self.tag}"
