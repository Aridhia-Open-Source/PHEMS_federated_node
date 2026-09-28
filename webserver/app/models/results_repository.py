"""Results repository model for task output storage."""
import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.models import sqla_column


class ResultsRepository(db.Model, BaseModel):
    __tablename__ = 'results_repositories'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    uri = sa.Column(sa.String(4096), unique=True, nullable=False)
    owned_by_federated_node = sa.Column(sa.Boolean, nullable=False, server_default='true')
    created_at = sqla_column.created_at()
    updated_at = sqla_column.updated_at()

    projects = relationship('Project', back_populates='results_repository')

    def __init__(self, uri: str, owned_by_federated_node: bool = True, **kwargs):
        self.uri = uri
        self.owned_by_federated_node = owned_by_federated_node

    def __repr__(self):
        return f'<ResultsRepository ({self.uri})>'
