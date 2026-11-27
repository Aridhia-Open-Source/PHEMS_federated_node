import json
from http import HTTPStatus
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from fednode.clients.nexus.models import TaskCompute
from app.helpers.const import (
    SPEC_RAW_MAX_BYTES,
    TASK_COMPUTE_LIMITS,
    TASK_ENV_KEY_REGEX,
    TASK_ENV_MAX_BYTES,
    TASK_ENV_RESERVED_KEYS,
    TASK_ENV_RESERVED_PREFIXES,
    TASK_IMAGE_MAX_LENGTH,
    TASK_NAME_MAX_LENGTH,
    TASK_TAG_KEY_REGEX,
)
from app.helpers.exceptions import InvalidRequest

EnvKey = Annotated[str, StringConstraints(pattern=TASK_ENV_KEY_REGEX)]
TagKey = Annotated[str, StringConstraints(pattern=TASK_TAG_KEY_REGEX)]


class PrSpec(BaseModel):
    """What a client may set in the `spec` of a pull request spec file."""
    model_config = ConfigDict(extra="forbid")

    image: str = Field(
        min_length=1, max_length=TASK_IMAGE_MAX_LENGTH, description="The container image the task runs"
    )
    dataset: str | None = Field(
        default=None,
        description=(
            "The name of a dataset the project is assigned and has active. Without it the project's default "
            "dataset is used, if it has one"
        ),
    )
    env: dict[EnvKey, Any] = Field(
        default_factory=dict,
        description=(
            f"Environment variables of the task. A name has to match {TASK_ENV_KEY_REGEX}, and can't be "
            f"{', '.join(sorted(TASK_ENV_RESERVED_KEYS))} or start with {' or '.join(TASK_ENV_RESERVED_PREFIXES)}, "
            f"in any letter case. The env as JSON is at most {TASK_ENV_MAX_BYTES} bytes"
        ),
        # pydantic states the key pattern as patternProperties only, a key that doesn't match it is still not allowed
        json_schema_extra={"additionalProperties": False},
    )
    tags: dict[TagKey, str] = Field(
        default_factory=dict,
        description=f"Tags copied onto the task's run. A key has to match {TASK_TAG_KEY_REGEX}, a value is text",
        json_schema_extra={"additionalProperties": False},
    )
    config: dict | None = Field(
        default=None,
        description="A JSON object the task reads as a file, at the path in its CONFIG_PATH env. Contents are not checked",
    )
    compute: TaskCompute = Field(
        default_factory=TaskCompute, description="The CPU and memory the task asks for. Without it the defaults apply"
    )

    @field_validator("env")
    @classmethod
    def _validate_env(cls, env: dict) -> dict:
        for key in env:
            upper = key.upper()
            if upper in TASK_ENV_RESERVED_KEYS or upper.startswith(TASK_ENV_RESERVED_PREFIXES):
                raise ValueError(f"env key {key} is reserved")
        if len(json.dumps(env).encode()) > TASK_ENV_MAX_BYTES:
            raise ValueError(f"env is over the {TASK_ENV_MAX_BYTES} bytes limit")
        return env


class PrSpecFile(BaseModel):
    """A pull request spec file: a JSON object with a `spec` and, optionally, a `metadata`."""
    model_config = ConfigDict(extra="forbid")

    spec: PrSpec = Field(description="What the task runs")
    metadata: Any = Field(
        default=None,
        description=(
            "The client's own: any JSON value, not validated, kept with the task and delivered with the results. "
            f"The whole spec file is at most {SPEC_RAW_MAX_BYTES} bytes"
        ),
    )


class TaskSpecRequest(PrSpec):
    """
    The one normalised description of a task, whichever way it was requested: the PrSpec fields, the
    pull request spec file's metadata and, for the API only, a name, params and a repository. What is
    kept is the image, dataset, env, tags, config, compute and metadata, as a TaskSpec.
    """
    name: str | None = Field(default=None, max_length=TASK_NAME_MAX_LENGTH)
    params: dict = {}
    # The client's own, any JSON value, not checked
    metadata: Any = None
    repository: str | None = None

    @staticmethod
    def readable(error: ValidationError) -> str:
        """The errors of a spec, one per line of the message, without pydantic's links."""
        parts = []
        for e in error.errors():
            where = ".".join(str(part) for part in e["loc"])
            message = e["msg"].removeprefix("Value error, ")
            parts.append(f"{where}: {message}" if where else message)
        return "; ".join(parts)

    @classmethod
    def build(cls, **fields) -> "TaskSpecRequest":
        try:
            return cls.model_validate(fields, context={"limits": TASK_COMPUTE_LIMITS})
        except ValidationError as ve:
            raise InvalidRequest(
                f"Invalid task spec: {cls.readable(ve)}", HTTPStatus.UNPROCESSABLE_ENTITY
            ) from ve

    @classmethod
    def from_api_body(cls, body: dict) -> "TaskSpecRequest":
        """
        The API shape is TES-like: the image and env sit on the first executor. Its tags only
        name the dataset and are not kept. Its compute is the spec's, as in a pull request spec file.
        """
        executors = body.get("executors")
        if not isinstance(executors, list) or not executors or not isinstance(executors[0], dict):
            raise InvalidRequest("executors must be a non-empty list of objects", HTTPStatus.UNPROCESSABLE_ENTITY)
        # Support only for one executor at a time
        executor = executors[0]
        tags = body.get("tags") or {}
        return cls.build(
            # The API strips spaces from a task name
            name=(body.get("name") or "").replace(" ", "") or None,
            image=executor.get("image"),
            env=executor.get("env") or {},
            dataset=tags.get("dataset_name"),
            repository=body.get("repository"),
            compute=body.get("compute") or {},
        )

    @classmethod
    def from_pr_spec(cls, spec_raw: str) -> "TaskSpecRequest":
        """
        The pull request spec file is parsed as a PrSpecFile: any other key, at its top level or in its
        `spec`, is refused. Its `metadata` is any JSON value, kept as it is.
        """
        try:
            file = PrSpecFile.model_validate_json(spec_raw, context={"limits": TASK_COMPUTE_LIMITS})
        except ValidationError as ve:
            raise InvalidRequest(
                f"Invalid spec file: {cls.readable(ve)}", HTTPStatus.UNPROCESSABLE_ENTITY
            ) from ve
        return cls.build(**file.spec.model_dump(), metadata=file.metadata)
