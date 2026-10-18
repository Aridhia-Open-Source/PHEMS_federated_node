"""
A project's grant of a global dataset, holding the project's own state for it.
"""
import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.helpers.soft_delete import SoftDeleteMixin
from app.models import Models


class ProjectDataset(SoftDeleteMixin, db.Model, BaseModel):
    __tablename__ = 'project_datasets'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    project_id = sa.Column(sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False)
    dataset_id = sa.Column(sa.Integer, sa.ForeignKey('datasets.id', ondelete='RESTRICT'), nullable=False)
    # A person turned the dataset on or off for the project
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    # The controller withdrew the project's access. Never touches enabled, so a re-grant
    # restores the previous state.
    revoked = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())

    __table_args__ = (
        sa.Index(
            'uq_project_datasets_project_dataset', 'project_id', 'dataset_id',
            unique=True, postgresql_where=sa.text('deleted_at IS NULL')
        ),
    )

    project = relationship("Project", back_populates="dataset_assignments", foreign_keys=[project_id])
    dataset = relationship("Dataset", back_populates="project_assignments")

    def __init__(self, project_id: int, dataset_id: int, enabled: bool = True, revoked: bool = False):
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.enabled = enabled
        self.revoked = revoked

    @property
    def active(self) -> bool:
        return self.dataset.enabled and self.enabled and not self.revoked

    def add(self, commit=True):
        super().add(False)
        # The first dataset assigned to a project is what a task gets when it names only
        # the project. Later ones do not displace it.
        project = Models.Project.get_by_id(self.project_id)
        if project.default_dataset_id is None:
            project.default_dataset_id = self.dataset_id
            project.add(False)
        if commit:
            db.session.commit()
        return self

    def soft_delete(self):
        # The project's default is not a dataset it no longer has
        if self.project.default_dataset_id == self.dataset_id:
            self.project.default_dataset_id = None
        super().soft_delete()

    def __repr__(self):
        return f'<ProjectDataset {self.project_id}:{self.dataset_id}>'
