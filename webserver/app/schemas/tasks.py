from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, computed_field, model_validator
from datetime import datetime as dt

from sqlalchemy import select

from app.helpers.keycloak import Keycloak
from app.helpers.exceptions import InvalidRequest
from app.helpers.const import TASK_POD_RESULTS_PATH, TASK_POD_INPUTS_PATH
from app.helpers.keycloak import Keycloak
from app.helpers.exceptions import InvalidRequest
from app.models.dataset import Dataset
from app.models.container import Container
from app.models.request import RequestModel
from app.models.task import REVIEW_STATUS, Task
from app.helpers.base_model import get_db

class TaskBase(BaseModel):
    name: str
    docker_image: Optional[str] = None
    description: Optional[str] = None
    requested_by: Optional[str] = None

    # internal vars, not passed to the model
    executors: list[dict] = Field(default=[{}], exclude=True)
    inputs: dict = Field(default={}, exclude=True)
    outputs: dict = Field(default={}, exclude=True)
    resources: dict = Field(default={}, exclude=True)
    db_query: dict = Field(default={}, exclude=True)

    model_config = ConfigDict(from_attributes=True)


class TaskCreate(TaskBase):
    executors: List[dict]
    outputs: Optional[dict] = {}
    inputs: Optional[dict] = {}
    db_query: Optional[dict] = {}
    resources: Optional[dict] = {}
    from_controller: Optional[bool] = False

    # internal vars, not passed to the model
    repository: Optional[str] = Field(default=None, exclude=True)
    tags: Optional[dict] = Field(default={}, exclude=True)

    @model_validator(mode='before')
    @classmethod
    def extract_fields(cls, data: dict):
        executors = data["executors"][0]
        data["docker_image"] = executors["image"]

        # Docker image validation
        Container.validate_image_format(data["docker_image"], data["docker_image"])

        data["executors"] = data["executors"]
        data["from_controller"] = data.pop("task_controller", False)

        # Output volumes validation
        if not isinstance(data.get("outputs", {}), dict):
            raise InvalidRequest("\"outputs\" field must be a json object or dictionary")
        if not data.get("outputs", {}):
            data["outputs"] = {"results": TASK_POD_RESULTS_PATH}
        if not isinstance(data.get("inputs", {}), dict):
            raise InvalidRequest("\"inputs\" field must be a json object or dictionary")
        if not data.get("inputs", {}):
            data["inputs"] = {"inputs.csv": TASK_POD_INPUTS_PATH}

        # Validate resource values
        if "resources" in data:
            Task.validate_cpu_resources(
                data["resources"].get("limits", {}).get("cpu"),
                data["resources"].get("requests", {}).get("cpu")
            )
            Task.validate_memory_resources(
                data["resources"].get("limits", {}).get("memory"),
                data["resources"].get("requests", {}).get("memory")
            )
        if data.get("db_query") is not None and "query" not in data["db_query"]:
            raise InvalidRequest("`db_query` field must include a `query`")

        return data

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        name = (v or "").replace(" ", "")
        if not name:
            raise InvalidRequest("name is a mandatory field")

        return name


class TaskRead(TaskBase):
    id: int
    dataset_id: int
    status: str|dict = "scheduled"
    review_status: bool|None = Field(exclude=True)
    dataset_id: int
    created_at: Optional[dt] = None
    updated_at: Optional[dt] = None

    @computed_field
    @property
    def review(self) -> str:
        return REVIEW_STATUS[self.review_status]

class TaskFilters(BaseModel):
    id__lte: Optional[int] = None
    id__gte: Optional[int] = None
    name: Optional[str] = None
    docker_image: Optional[str] = None

    page: int = 1
    per_page: int = 25
