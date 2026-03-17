import re
from typing import Optional
from pydantic import BaseModel, ConfigDict, model_validator

from app.helpers.exceptions import InvalidRequest
from app.models.container import Container
from app.models.task import Task


class ContainerBase(BaseModel):
    name: str
    tag: Optional[str] = None
    sha: Optional[str] = None
    ml: bool = False
    dashboard: bool = False

    model_config = ConfigDict(from_attributes=True)


class ContainerCreate(ContainerBase):
    registry: str

    @model_validator(mode='before')
    @classmethod
    def extract_fields(cls, data: dict):
        if not (data.get("tag") or data.get("sha")):
            raise InvalidRequest("Make sure `tag` or `sha` are provided")

        img_with_tag = f"{data["name"]}:{data.get("tag")}"
        img_with_sha = f"{data["name"]}@{data.get("sha")}"

        cls.validate_image_format(img_with_tag, img_with_sha)
        return data

    @classmethod
    def validate_image_format(cls, img_with_tag, img_with_sha):
        if not (re.match(r'^((\w+|-|\.)\/?+)+:(\w+(\.|-)?)+$', img_with_tag) or re.match(r'^((\w+|-|\.)\/?+)+@sha256:.+$', img_with_sha)):
            raise InvalidRequest(
                f"{img_with_tag} does not have a tag. Please provide one in the format <image>:<tag> or <image>@sha256.."
            )

class ContainerUpdate(BaseModel):
    ml: Optional[bool] = None
    dashboard: Optional[bool] = None


class ContainerRead(ContainerBase):
    id: int
    registry_id: int


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
