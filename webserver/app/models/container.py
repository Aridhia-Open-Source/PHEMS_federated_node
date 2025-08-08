import re
from sqlalchemy import Column, Integer, Boolean, String, ForeignKey
from sqlalchemy.orm import relationship
from app.helpers.base_model import BaseModel, db
from app.models.registry import Registry
from app.helpers.exceptions import ContainerException, ContainerRegistryException, InvalidRequest


class Container(db.Model, BaseModel):
    __tablename__ = 'containers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    tag = Column(String(256), nullable=False)
    ml = Column(Boolean(), default=False)
    dashboard = Column(Boolean(), default=False)

    registry_id = Column(Integer, ForeignKey(Registry.id, ondelete='CASCADE'))
    registry = relationship("Registry")

    registry_regex = r'((\w+|-|\.)+\/)'
    image_tag_regex = r'((\w+|-|\.)\/?)+:(\w+(\.|-)?)+$'

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

    @classmethod
    def validate_regex_format(cls, full_name:str, with_registry:bool=False) -> bool:
        if with_registry:
            return re.match(f'^{cls.registry_regex}{cls.image_tag_regex}', full_name)

        return re.match(f'^{cls.image_tag_regex}', full_name)

    @classmethod
    def validate(cls, data:dict):
        data = super().validate(data)

        reg = Registry.query.filter(Registry.url==data["registry"]).one_or_none()
        if reg is None:
            raise ContainerRegistryException(f"Registry {data["registry"]} could not be found")
        data["registry"] = reg

        img_with_tag = f"{data["name"]}:{data["tag"]}"
        if not cls.validate_regex_format(img_with_tag):
            raise InvalidRequest(
                f"{img_with_tag} does not have a tag. Please provide one in the format <image>:<tag>"
            )
        return data

    def full_image_name(self):
        return f"{self.registry.url}/{self.name}:{self.tag}"

    @classmethod
    def get_from_full_name(cls, full_name:str):
        """
        From the full name (including the registry) return the DB object
        """
        if not cls.validate_regex_format(full_name, with_registry=True):
            raise ContainerException(
                f"Image name {full_name} doesn't have the proper format. Ensure it has <registry>/<container>:<tag>",
                code=400
            )

        im_split = full_name.split("/")
        reg_name = im_split[0]
        name = "/".join(im_split[1:])
        name, tag = name.split(":")

        img = cls.query.join(Registry).filter(
            cls.name == name,
            cls.tag == tag,
            Registry.url == reg_name
        ).one_or_none()
        return img
