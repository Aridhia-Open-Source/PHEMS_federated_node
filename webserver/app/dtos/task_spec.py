from pydantic import BaseModel, ConfigDict, ValidationError

from app.helpers.exceptions import InvalidRequest


class TaskSpec(BaseModel):
    """
    The one normalised description of a task, whichever way it was requested.
    It is stored once, on Task.spec.
    """
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    image: str
    env: dict = {}
    params: dict = {}
    dataset: str | None = None
    tags: dict = {}
    resources: dict = {}
    repository: str | None = None

    @classmethod
    def build(cls, **fields) -> "TaskSpec":
        try:
            return cls(**fields)
        except ValidationError as ve:
            raise InvalidRequest(f"Invalid task spec: {ve}") from ve

    @classmethod
    def from_api_body(cls, body: dict) -> "TaskSpec":
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
    def from_pr_spec(cls, spec: dict) -> "TaskSpec":
        """
        The pull request shape is flat, and names the image as either `image` or `docker_image`.
        """
        fields = dict(spec)
        docker_image = fields.pop("docker_image", None)
        fields["image"] = fields.get("image") or docker_image
        return cls.build(**fields)
