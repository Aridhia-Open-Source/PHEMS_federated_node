from pydantic import BaseModel, ConfigDict, Field, model_validator


class PullRequestSpec(BaseModel):
    """
    The task spec a pull request carries in its spec file. It names the image as either
    `image` or `docker_image`; the model normalises it to `image`.
    """
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    image: str = Field(min_length=1)
    env: dict = {}
    params: dict = {}
    dataset: str | None = None
    tags: dict = {}
    resources: dict = {}
    repository: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalise_image(cls, data):
        if not isinstance(data, dict):
            return data
        fields = dict(data)
        docker_image = fields.pop("docker_image", None)
        fields["image"] = fields.get("image") or docker_image
        return fields
