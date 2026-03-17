import re
from sqlalchemy import ForeignKey, Integer, Boolean, String
from sqlalchemy.orm import Mapped, relationship, mapped_column
from app.helpers.base_model import BaseModel
from app.models.registry import Registry
from app.helpers.exceptions import InvalidRequest


class Container(BaseModel):
    __tablename__ = 'containers'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    tag: Mapped[str] = mapped_column(String(256), nullable=True)
    sha: Mapped[str] = mapped_column(String(256), nullable=True)
    ml: Mapped[bool] = mapped_column(Boolean(), default=False)
    dashboard: Mapped[bool] = mapped_column(Boolean(), default=False)

    registry_id: Mapped[int] = mapped_column(Integer, ForeignKey(Registry.id, ondelete='CASCADE'))
    registry: Mapped["Registry"] = relationship("Registry", back_populates="containers")

    @classmethod
    def validate_image_format(cls, img_with_tag, img_with_sha):
        if not (
            re.match(r'^((\w+|-|\.)\/?+)+:(\w+(\.|-)?)+$', img_with_tag)\
            or re.match(r'^((\w+|-|\.)\/?+)+@sha256:.+$', img_with_sha)
        ):
            raise InvalidRequest(
                f"{img_with_tag} does not have a tag. Please provide one in the format <image>:<tag> or <image>@sha256.."
            )

    def full_image_name(self):
        if self.sha:
            return f"{self.registry.url}/{self.name}@{self.sha}"

        return f"{self.registry.url}/{self.name}:{self.tag}"
