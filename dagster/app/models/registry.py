import re

from pydantic import BaseModel, ConfigDict, computed_field


class Registry(BaseModel):
    """Container registry data from backend API."""
    model_config = ConfigDict(extra="allow")

    id: int
    url: str
    active: bool = True
    needs_auth: bool = True

    @computed_field
    @property
    def secret_name(self) -> str:
        """The dockerconfigjson secret the backend keeps for this registry."""
        return re.sub(r'[\W_]+', '-', self.host)

    @computed_field
    @property
    def host(self) -> str:
        return re.sub(r'^http(s)?://', '', self.url)

    def matches_image(self, image: str) -> bool:
        return image == self.host or image.startswith(f"{self.host}/")

    @classmethod
    def secret_for_image(cls, image: str, registries: list["Registry"]) -> str | None:
        """
        The pull secret for an image, or None if no configured registry serves it.

        Shortest matching prefix wins, as the backend's own lookup does.
        """
        matches = sorted(
            (r for r in registries if r.matches_image(image)),
            key=lambda r: len(r.host),
        )
        return matches[0].secret_name if matches else None
