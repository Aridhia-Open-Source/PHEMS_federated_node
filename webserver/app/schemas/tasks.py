import re
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, computed_field, model_validator
from datetime import datetime as dt


from app.helpers.exceptions import InvalidRequest
from app.helpers.const import CPU_RESOURCE_REGEX, MEMORY_RESOURCE_REGEX, MEMORY_UNITS, TASK_POD_INPUTS_PATH, REVIEW_STATUS
from app.helpers.exceptions import InvalidRequest
from app.helpers.settings import settings
from app.schemas.containers import ContainerCreate


class TaskBase(BaseModel):
    name: str
    docker_image: Optional[str] = None
    description: Optional[str] = None

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

    @classmethod
    def validate_cpu_resources(cls, limit_value:str, request_value:str):
        """
        Given a value for the cpu limits or requests, make sure it conforms to
        accepted k8s values.
        e.g.
            - 100m
            - 0.1
            - 1
        """
        for value in [limit_value, request_value]:
            if value is None or value == "":
                return
            cpu_error_message = f"Cpu resource value {value} not valid."
            if not re.match(CPU_RESOURCE_REGEX, value):
                raise InvalidRequest(cpu_error_message)
        if cls.convert_cpu_values_to_int(limit_value) < cls.convert_cpu_values_to_int(request_value):
            raise InvalidRequest("Cpu limit cannot be lower than request")

    @classmethod
    def validate_memory_resources(cls, limit_value:str, request_value:str):
        """
        Given a value for the memory limits or requests, make sure it conforms to
        accepted k8s values.
        e.g.
            - 128974848
            - 129e6
            - 129M
            - 128974848000m
            - 123Mi
        """
        for value in [limit_value, request_value]:
            if value is None or value == "":
                return
            memory_error_msg = f"Memory resource value {value} not valid."
            if not re.match(MEMORY_RESOURCE_REGEX, value):
                raise InvalidRequest(memory_error_msg)
        if cls.convert_memory_values_to_int(limit_value) < cls.convert_memory_values_to_int(request_value):
            raise InvalidRequest("Memory limit cannot be lower than request")

    @classmethod
    def convert_cpu_values_to_int(cls, val:str) -> float:
        """
        Since cpu values can come with different units,
        they should be standardized to float, so that they can
        be compared and validated to have limits > requests
        """
        if re.match(r'^\d+$', val):
            return float(val)
        if re.match(r'^\d+\.\d+$', val):
            return float(val)
        return float(val[:-1]) / 1000

    @classmethod
    def convert_memory_values_to_int(cls, val:str) -> int:
        """
        Since memory values can come with different units,
        they should be standardized to int, so that they can
        be compared and validated to have limits > requests
        """
        if re.match(r'^\d+$', val):
            return int(val)
        if re.match(r'^\d+e\d+$', val):
            base, exp = val.split('e')
            return int(base) * 10**(int(exp))

        # Other accepted formats trail with some letters
        unit_index = re.search(r'[^\d]+$', val).span()[0]
        base = val[:unit_index]
        unit = val[unit_index:]
        return int(base) * MEMORY_UNITS[unit]

    @model_validator(mode='before')
    @classmethod
    def extract_fields(cls, data: dict):
        executors = data["executors"][0]
        data["docker_image"] = executors["image"]

        # Docker image validation
        ContainerCreate.validate_image_format(data["docker_image"], data["docker_image"])

        data["executors"] = data["executors"]
        data["from_controller"] = data.pop("task_controller", False)

        # Output volumes validation
        if not isinstance(data.get("outputs", {}), dict):
            raise InvalidRequest("\"outputs\" field must be a json object or dictionary")
        if not data.get("outputs", {}):
            data["outputs"] = {"results": settings.task_pod_results_path}
        if not isinstance(data.get("inputs", {}), dict):
            raise InvalidRequest("\"inputs\" field must be a json object or dictionary")
        if not data.get("inputs", {}):
            data["inputs"] = {"inputs.csv": TASK_POD_INPUTS_PATH}

        # Validate resource values
        if "resources" in data:
            cls.validate_cpu_resources(
                data["resources"].get("limits", {}).get("cpu"),
                data["resources"].get("requests", {}).get("cpu")
            )
            cls.validate_memory_resources(
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
    requested_by: Optional[str] = None
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
