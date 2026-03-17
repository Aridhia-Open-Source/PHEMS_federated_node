import re
from sqlalchemy import Column, Integer, Boolean, String, ForeignKey
from sqlalchemy.orm import relationship
from app.helpers.base_model import BaseModel, db
from app.models.registry import Registry
from app.helpers.exceptions import InvalidRequest


class Container(db.Model, BaseModel):
    __tablename__ = 'containers'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    tag = Column(String(256), nullable=True)
    sha = Column(String(256), nullable=True)
    ml = Column(Boolean(), default=False)
    dashboard = Column(Boolean(), default=False)

    registry_id = Column(Integer, ForeignKey(Registry.id, ondelete='CASCADE'))
    registry = relationship("Registry")

    def full_image_name(self):
        if self.sha:
            return f"{self.registry.url}/{self.name}@{self.sha}"

        return f"{self.registry.url}/{self.name}:{self.tag}"
