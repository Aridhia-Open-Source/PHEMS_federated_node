from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship
from app.helpers.base_model import BaseModel, db


class Repository(db.Model, BaseModel):
    __tablename__ = 'repositories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uri = Column(String(4096), unique=True, nullable=False)
    pr_cursor = Column(Integer, default=0, nullable=False)
    base_branch = Column(String(256), nullable=True, default='main')
    polled_at = Column(DateTime, nullable=True)

    datasets = relationship("Dataset", back_populates="repository")

    def __init__(self, uri: str, base_branch: str = 'main'):
        self.uri = uri.lower()
        self.pr_cursor = 0
        self.base_branch = base_branch

    def __repr__(self):
        return f'<Repository ({self.uri})>'
