"""
A project's resource for a global secret, holding the project's own state for it. Only the
reference is assigned: the values stay in the secret store.
"""
import sqlalchemy as sa
from sqlalchemy.orm import relationship

from app.helpers.base_model import BaseModel, db
from app.helpers.soft_delete import SoftDeleteMixin


class ProjectSecret(SoftDeleteMixin, db.Model, BaseModel):
    __tablename__ = 'project_secrets'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    project_id = sa.Column(sa.Integer, sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=False)
    secret_id = sa.Column(sa.Integer, sa.ForeignKey('secrets.id', ondelete='RESTRICT'), nullable=False)
    # A person turned the secret on or off for the project
    enabled = sa.Column(sa.Boolean, nullable=False, default=True, server_default=sa.true())
    # The controller withdrew the project's access. Never touches enabled, so a re-grant
    # restores the previous state.
    revoked = sa.Column(sa.Boolean, nullable=False, default=False, server_default=sa.false())

    __table_args__ = (
        sa.Index(
            'uq_project_secrets_project_secret', 'project_id', 'secret_id',
            unique=True, postgresql_where=sa.text('deleted_at IS NULL')
        ),
    )

    project = relationship("Project", back_populates="secret_assignments")
    secret = relationship("Secret", back_populates="project_assignments")

    def __init__(self, project_id: int, secret_id: int, enabled: bool = True, revoked: bool = False):
        self.project_id = project_id
        self.secret_id = secret_id
        self.enabled = enabled
        self.revoked = revoked

    @property
    def active(self) -> bool:
        return self.secret.enabled and self.enabled and not self.revoked

    def __repr__(self):
        return f'<ProjectSecret {self.project_id}:{self.secret_id}>'
