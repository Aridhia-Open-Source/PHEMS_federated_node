import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.helpers.const import (
    TASK_ENV_KEY_REGEX, TASK_ENV_MAX_BYTES, TASK_ENV_RESERVED_KEYS, TASK_ENV_RESERVED_PREFIXES,
    TASK_IMAGE_MAX_LENGTH, TASK_NAME_MAX_LENGTH, TASK_TAG_KEY_REGEX
)
from app.helpers.exceptions import InvalidRequest

# What a pull request spec file may hold: at its top level, and inside its `spec`
PR_FILE_KEYS = {"spec", "metadata"}
PR_SPEC_KEYS = {"image", "dataset", "env", "tags", "config"}


class TaskSpecRequest(BaseModel):
    """
    The one normalised description of a task, whichever way it was requested. Only the
    image, the dataset, the env, the tags, the config and the metadata are kept, as a TaskSpec.
    A pull request spec file can only set those, see from_pr_spec.
    """
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=TASK_NAME_MAX_LENGTH)
    image: str = Field(min_length=1, max_length=TASK_IMAGE_MAX_LENGTH)
    env: dict = {}
    params: dict = {}
    dataset: str | None = None
    tags: dict[str, str] = {}
    # A JSON object that is the task's own, its contents are not checked
    config: dict | None = None
    # The client's own, any JSON value, not checked
    metadata: Any = None
    repository: str | None = None

    @field_validator("env")
    @classmethod
    def _validate_env(cls, env: dict) -> dict:
        for key in env:
            if not re.fullmatch(TASK_ENV_KEY_REGEX, key):
                raise ValueError(f"env key {key!r} must match {TASK_ENV_KEY_REGEX}")
            upper = key.upper()
            if upper in TASK_ENV_RESERVED_KEYS or upper.startswith(TASK_ENV_RESERVED_PREFIXES):
                raise ValueError(f"env key {key} is reserved")
        if len(json.dumps(env).encode()) > TASK_ENV_MAX_BYTES:
            raise ValueError(f"env is over the {TASK_ENV_MAX_BYTES} bytes limit")
        return env

    @field_validator("tags")
    @classmethod
    def _validate_tags(cls, tags: dict[str, str]) -> dict[str, str]:
        for key in tags:
            if not re.fullmatch(TASK_TAG_KEY_REGEX, key):
                raise ValueError(f"tag key {key} is not valid, it must match {TASK_TAG_KEY_REGEX}")
        return tags

    @classmethod
    def build(cls, **fields) -> "TaskSpecRequest":
        try:
            return cls(**fields)
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid task spec: {ve}") from ve

    @classmethod
    def from_api_body(cls, body: dict) -> "TaskSpecRequest":
        """
        The API shape is TES-like: the image and env sit on the first executor. Its tags only
        name the dataset and its resources are only validated (see Task.validate), neither is kept.
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
            repository=body.get("repository"),
        )

    @classmethod
    def from_pr_spec(cls, spec_raw: str) -> "TaskSpecRequest":
        """
        The pull request spec file is a JSON object with a `spec` and, optionally, a `metadata`,
        which is the client's own: any JSON value, kept as it is and not validated. Any other key
        at the top level, or in the `spec` beyond PR_SPEC_KEYS, is refused.
        """
        try:
            file = json.loads(spec_raw)
        except ValueError as e:
            raise InvalidRequest(f"Invalid spec file: {type(e).__name__}: {e}") from e
        if not isinstance(file, dict):
            raise InvalidRequest("Invalid spec file: must be an object")
        if unknown := file.keys() - PR_FILE_KEYS:
            raise InvalidRequest(f"Invalid spec file: unknown key(s) {sorted(unknown)}, only {sorted(PR_FILE_KEYS)} are allowed")
        if "spec" not in file:
            raise InvalidRequest("Invalid spec file: spec is required")
        spec = file["spec"]
        if not isinstance(spec, dict):
            raise InvalidRequest("Invalid spec file: spec must be an object")
        if unknown := spec.keys() - PR_SPEC_KEYS:
            raise InvalidRequest(f"Invalid spec file: unknown key(s) {sorted(unknown)} in spec, only {sorted(PR_SPEC_KEYS)} are allowed")
        return cls.build(**spec, metadata=file.get("metadata"))
