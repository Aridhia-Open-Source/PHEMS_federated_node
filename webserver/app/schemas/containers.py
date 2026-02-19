from typing import Optional
from pydantic import BaseModel, ConfigDict, model_validator

from app.helpers.exceptions import ContainerRegistryException, InvalidRequest
from app.models.registry import Registry
from app.models.container import Container


class ContainerBase(BaseModel):
    name: str
    tag: Optional[str] = None
    sha: Optional[str] = None
    ml: bool
    dashboard: bool
    registry_id: int

    model_config = ConfigDict(from_attributes=True)

class ContainerCreate(ContainerBase):
    @model_validator(mode='before')
    @classmethod
    def extract_fields(cls, data: dict):
        if not (data.get("tag") or data.get("sha")):
            raise InvalidRequest("Make sure `tag` or `sha` are provided")

        reg: Registry = Registry.query.filter(Registry.url==data["registry"]).one_or_none()
        if reg is None:
            raise ContainerRegistryException(f"Registry {data["registry"]} could not be found")
        data["registry_id"] = reg.id

        img_with_tag = f"{data["name"]}:{data.get("tag")}"
        img_with_sha = f"{data["name"]}@{data.get("sha")}"

        Container.validate_image_format(img_with_tag, img_with_sha)
        return data


class ContainerUpdate(BaseModel):
    ml: Optional[bool] = None
    dashboard: Optional[bool] = None


class ContainerRead(ContainerBase):
    id: int


class ContainerFilters(BaseModel):
    id__lte: Optional[int] = None
    id__gte: Optional[int] = None
    registry_id: Optional[int] = None
    ml: Optional[bool] = None
    dashboard: Optional[bool] = None
    tag: Optional[str] = None
    sha: Optional[str] = None
    name: Optional[str] = None

    page: int = 1
    per_page: int = 25
