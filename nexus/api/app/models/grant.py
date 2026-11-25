"""
Grants (ADR 0037): which user or group may do what to a project or a global record. Recorded here; the Cedar
check that reads them comes later. Nobody writes the table directly: grants come from creating a record
(helpers/ownership.set_owner), the grants routes (grants_api) and claiming.
"""
import sqlalchemy as sa

from app.database.base_model import BaseModel, db
from app.models import sqla_column

# The authz_type of every model with grants (OwnedMixin)
OBJECT_TYPES = ('Project', 'Dataset', 'GitProvider', 'Secret', 'TriggerRepository', 'ResultsRepository')
# read < assign, execute, operate, write < manage
RELATIONS = ('read', 'assign', 'execute', 'operate', 'write', 'manage')
SUBJECT_TYPES = ('user', 'group')
MANAGE = 'manage'
USER = 'user'
GROUP = 'group'


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class Grant(db.Model, BaseModel):
    """One relation on one record for one user (Keycloak user id) or group (Keycloak group path)."""
    __tablename__ = 'grants'
    __table_args__ = (
        sa.CheckConstraint(_in('object_type', OBJECT_TYPES), name='ck_grants_object_type'),
        sa.CheckConstraint(_in('relation', RELATIONS), name='ck_grants_relation'),
        sa.CheckConstraint(_in('subject_type', SUBJECT_TYPES), name='ck_grants_subject_type'),
        sa.UniqueConstraint(
            'object_type', 'object_id', 'relation', 'subject_type', 'subject_id',
            name='uq_grants_object_relation_subject',
        ),
        sa.Index('ix_grants_object', 'object_type', 'object_id'),
        sa.Index('ix_grants_subject', 'subject_type', 'subject_id'),
    )

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    # The record's authz_type; no foreign key, as it points at many tables
    object_type = sa.Column(sa.String(64), nullable=False)
    object_id = sa.Column(sa.Integer, nullable=False)
    relation = sa.Column(sa.String(16), nullable=False)
    subject_type = sa.Column(sa.String(16), nullable=False)
    subject_id = sa.Column(sa.String(255), nullable=False)
    # Naive UTC, like every other timestamp here; None never expires
    expires_at = sa.Column(sa.DateTime(timezone=False), nullable=True)
    created_by_id = sa.Column('created_by', sa.String(255), sa.ForeignKey('users.id'), nullable=True)
    created_at = sqla_column.created_at()

    @classmethod
    def of(cls, record) -> sa.Select:
        """The select of a record's grants."""
        return sa.select(cls).where(cls.object_type == record.authz_type, cls.object_id == record.id)

    @classmethod
    def delete_for(cls, record) -> None:
        """Deletes a record's grants in the current transaction."""
        db.session.execute(
            sa.delete(cls).where(cls.object_type == record.authz_type, cls.object_id == record.id)
        )

    def __repr__(self):
        return (
            f'<Grant {self.relation} on {self.object_type} {self.object_id} '
            f'for {self.subject_type} {self.subject_id}>'
        )
