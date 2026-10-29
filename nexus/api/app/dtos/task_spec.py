import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.helpers.const import (
    TASK_ENV_KEY_REGEX, TASK_ENV_MAX_BYTES, TASK_ENV_RESERVED_KEYS,
    TASK_IMAGE_MAX_LENGTH, TASK_NAME_MAX_LENGTH
)
from app.helpers.exceptions import InvalidRequest


class TaskSpecRequest(BaseModel):
    """
    The one normalised description of a task, whichever way it was requested. Only the
    image, the dataset and the env are kept, as a TaskSpec.
    """
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=TASK_NAME_MAX_LENGTH)
    image: str = Field(max_length=TASK_IMAGE_MAX_LENGTH)
    env: dict = {}
    params: dict = {}
    dataset: str | None = None
    tags: dict = {}
    resources: dict = {}
    repository: str | None = None

    @field_validator("env")
    @classmethod
    def _validate_env(cls, env: dict) -> dict:
        for key in env:
            if not re.fullmatch(TASK_ENV_KEY_REGEX, key):
                raise ValueError(f"env key {key!r} must match {TASK_ENV_KEY_REGEX}")
            if key in TASK_ENV_RESERVED_KEYS:
                raise ValueError(f"env key {key} is reserved")
        if len(json.dumps(env).encode()) > TASK_ENV_MAX_BYTES:
            raise ValueError(f"env is over the {TASK_ENV_MAX_BYTES} bytes limit")
        return env

    @classmethod
    def build(cls, **fields) -> "TaskSpecRequest":
        try:
            return cls(**fields)
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid task spec: {ve}") from ve

    @classmethod
    def from_api_body(cls, body: dict) -> "TaskSpecRequest":
        """
        The API shape is TES-like: the image and env sit on the first executor.
        """
        executors = body.get("executors")
        if not isinstance(executors, list) or not executors or not isinstance(executors[0], dict):
            raise InvalidRequest("executors must be a non-empty list of objects")
        # Support only for one executor at a time
        executor = executors[0]
        tags = body.get("tags") or {}
        return cls.build(
            # The API strips spaces from a task name
            name=(body.get("name") or "").replace(" ", "") or None,
            image=executor.get("image"),
            env=executor.get("env") or {},
            dataset=tags.get("dataset_name"),
            tags=tags,
            resources=body.get("resources") or {},
            repository=body.get("repository"),
        )

    @classmethod
    def from_pr_spec(cls, spec_raw: str) -> "TaskSpecRequest":
        """
        The pull request spec file is JSON with a flat `spec`, which names the image as
        either `image` or `docker_image`.
        """
        try:
            fields = json.loads(spec_raw)["spec"]
        except (ValueError, KeyError, TypeError) as e:
            raise InvalidRequest(f"Invalid spec file: {type(e).__name__}: {e}") from e
        if not isinstance(fields, dict):
            raise InvalidRequest("Invalid spec file: spec must be an object")
        fields = dict(fields)
        docker_image = fields.pop("docker_image", None)
        fields["image"] = fields.get("image") or docker_image
        return cls.build(**fields)
