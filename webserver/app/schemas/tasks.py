from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, computed_field, model_validator
from datetime import datetime as dt

from app.helpers.keycloak import Keycloak
from app.helpers.exceptions import InvalidRequest
from app.helpers.const import TASK_POD_RESULTS_PATH, TASK_POD_INPUTS_PATH
from app.helpers.keycloak import Keycloak
from app.helpers.exceptions import InvalidRequest
from app.models.dataset import Dataset
from app.models.container import Container
from app.models.request import Request
from app.models.task import REVIEW_STATUS, Task

class TaskBase(BaseModel):
    name: str
    docker_image: Optional[str] = None
    description: Optional[str] = None
    requested_by: Optional[str] = None
    dataset_id: int

    # internal vars, not validated
    _executors: dict = PrivateAttr()
    _inputs: dict = PrivateAttr()
    _outputs: dict = PrivateAttr()
    _resources: dict = PrivateAttr()
    _db_query: dict = PrivateAttr()

    model_config = ConfigDict(from_attributes=True)


class TaskCreate(TaskBase):
    executors: List[dict]
    outputs: Optional[dict] = {}
    inputs: Optional[dict] = {}
    db_query: Optional[dict] = {}
    resources: Optional[dict] = {}
    from_controller: Optional[bool] = False

    @model_validator(mode='before')
    @classmethod
    def extract_fields(cls, data: dict):
        executors = data["executors"][0]
        data["docker_image"] = executors["image"]
        repository = data.pop("repository", None)
        kc_client = Keycloak()
        user_token = Keycloak.get_token_from_headers()

        decoded_token = kc_client.decode_token(user_token)
        data["requested_by"] = kc_client.get_user_by_email(decoded_token["email"])["id"]
        user = kc_client.get_user_by_id(data["requested_by"])

        # Dataset validation
        if repository:
            ds: Dataset = Dataset.query.filter(
                Dataset.repository.ilike(repository)
            ).one_or_none()
            if ds is None:
                raise InvalidRequest(f"No datasets linked with the repository {repository}")

            data["dataset_id"] = ds.id

        elif kc_client.is_user_admin(user_token):
            ds_id = data.get("tags", {}).get("dataset_id")
            ds_name = data.get("tags", {}).get("dataset_name")
            if ds_name or ds_id:
                data["dataset_id"] = Dataset.get_dataset_by_name_or_id(name=ds_name, id=ds_id).id
            else:
                raise InvalidRequest("Administrators need to provide `tags.dataset_id` or `tags.dataset_name`")
        else:
            data["dataset_id"] = Request.get_active_project(
                data["project_name"],
                user["id"]
            ).dataset.id

        # Docker image validation
        Container.validate_image_format(data["docker_image"], data["docker_image"])
        data["docker_image"] = Task.get_image_with_repo(data["docker_image"])

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
            data["_resources"] = data["resources"]
        if data.get("db_query") is not None and "query" not in data["db_query"]:
            raise InvalidRequest("`db_query` field must include a `query`")

        data["db_query"] = data.pop("db_query", {})
        return data

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str):
        name = (v or "").replace(" ", "")
        if not name:
            raise InvalidRequest("name is a mandatory field")

        return name


class TaskRead(TaskBase):
    id: int
    dataset_id: int
    status: str|dict = "scheduled"
    review_status: bool|None = Field(exclude=True)
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
