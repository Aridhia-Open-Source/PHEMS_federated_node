"""
A project's grant of a global results repository, holding the project's own state for it:
where its results go, and whether it may use it.
"""
import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.helpers.soft_delete import SoftDeleteMixin


class ProjectResultsRepository(SoftDeleteMixin, db.Model, BaseModel):
    __tablename__ = 'project_results_repositories'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    # One results repository per project for now.
    project_id = sa.Column(
        sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False
    )
    results_repository_id = sa.Column(
        sa.Integer, sa.ForeignKey('results_repositories.id', ondelete='RESTRICT'), nullable=False
    )
    target_dir = sa.Column(sa.String(4096), nullable=False)
    owned_by_federated_node = sa.Column(sa.Boolean, nullable=False, server_default=sa.true())
    # A person turned the repository on or off for the project
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    # The controller withdrew the project's access. Never touches enabled, so a re-grant
    # restores the previous state.
    revoked = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())

    __table_args__ = (
        sa.Index(
            'uq_project_results_repositories_project', 'project_id',
            unique=True, postgresql_where=sa.text('deleted_at IS NULL')
        ),
    )

    project = relationship("Project", back_populates="results_repository_assignments")
    results_repository = relationship("ResultsRepository", back_populates="project_assignments")
    results = relationship("Result", back_populates="assignment")

    def __init__(
        self,
        project_id: int,
        results_repository_id: int,
        target_dir: str,
        owned_by_federated_node: bool = True,
        enabled: bool = True,
        revoked: bool = False,
    ):
        self.project_id = project_id
        self.results_repository_id = results_repository_id
        self.target_dir = target_dir
        self.owned_by_federated_node = owned_by_federated_node
        self.enabled = enabled
        self.revoked = revoked

    @property
    def active(self) -> bool:
        return self.results_repository.active and self.enabled and not self.revoked

    def __repr__(self):
        return f'<ProjectResultsRepository {self.project_id}:{self.results_repository_id}>'
