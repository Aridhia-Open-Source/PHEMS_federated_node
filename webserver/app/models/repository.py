from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from app.helpers.base_model import BaseModel, db


class Repository(db.Model, BaseModel):
    __tablename__ = 'repositories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uri = Column(String(4096), unique=True, nullable=False)
    last_pr_number = Column(Integer, default=0, nullable=False)

    datasets = relationship("Dataset", back_populates="repository")

    def __init__(self, uri: str):
        self.uri = uri.lower()
        self.last_pr_number = 0

    def __repr__(self):
        return f'<Repository ({self.uri})>'
