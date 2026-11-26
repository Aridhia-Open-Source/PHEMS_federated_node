"""
A Keycloak identity that has called nexus-api (ADR 0036). Identity only: what a caller may do stays in
Keycloak. Records point at it to say who created them and who owns them.
"""
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import declared_attr, relationship
from sqlalchemy.sql import func

from app.database.base_model import BaseModel, db
from app.models.grant import OBJECT_TYPES, Grant


class User(db.Model, BaseModel):
    """One row per Keycloak identity that has called nexus-api, written by get_caller."""
    __tablename__ = 'users'

    # The Keycloak user id
    id = sa.Column(sa.String(255), primary_key=True)
    username = sa.Column(sa.String(255), nullable=False)
    created_at = sa.Column(sa.DateTime(timezone=False), nullable=False, server_default=func.now())
    last_seen_at = sa.Column(sa.DateTime(timezone=False), nullable=False, server_default=func.now())

    @classmethod
    def seen(cls, user_id: str, username: str) -> "User":
        """
        Creates the user, or refreshes its username and last_seen_at, in one statement, and commits. A row seen
        in the last minute under the same username is left alone, so most calls write nothing. It still commits,
        as the conflict locks the row either way.
        """
        stmt = insert(cls).values(id=user_id, username=username)
        stmt = stmt.on_conflict_do_update(
            index_elements=[cls.id],
            set_={"username": username, "last_seen_at": func.now()},
            where=sa.or_(
                cls.last_seen_at < func.now() - timedelta(minutes=1),
                cls.username.is_distinct_from(stmt.excluded.username),
            ),
        ).returning(cls)
        user = db.session.scalars(
            stmt, execution_options={"populate_existing": True}
        ).one_or_none() or db.session.get(cls, user_id)
        db.session.commit()
        return user

    def __repr__(self):
        return f'<User ({self.username})>'


class CreatedByMixin:
    """
    Who created a record (ADR 0037): created_by is set once, on create, for audit, and grants nothing. Every
    record a caller creates has it; creating routes set it through helpers/ownership.
    """

    @declared_attr
    def created_by_id(cls):  # pylint: disable=no-self-argument
        """The user that created the record (column created_by)."""
        return sa.Column('created_by', sa.String(255), sa.ForeignKey('users.id'), nullable=True)

    @declared_attr
    def created_by(cls):  # pylint: disable=no-self-argument
        """The created_by user."""
        return relationship("User", foreign_keys=f"[{cls.__name__}.created_by_id]")


class OwnedMixin(CreatedByMixin):
    """
    A project or a global record, which has grants (ADR 0037). owned_by is who is responsible for it now; it
    changes when SuperUser claims or re-assigns it, and grants nothing by itself. A model declares authz_type,
    the name its grants and the policies use; it is never derived from the class or table name.
    """
    authz_type: str

    def __init_subclass__(cls, **kwargs):
        if cls.__dict__.get('authz_type') not in OBJECT_TYPES:
            raise TypeError(f"{cls.__name__} must declare authz_type, one of {OBJECT_TYPES}")
        super().__init_subclass__(**kwargs)

    def soft_delete(self):
        """Deleting the record deletes its grants, in the same transaction (before SoftDeleteMixin in the bases)."""
        Grant.delete_for(self)
        super().soft_delete()

    @declared_attr
    def owned_by_id(cls):  # pylint: disable=no-self-argument
        """The user responsible for the record (column owned_by)."""
        return sa.Column('owned_by', sa.String(255), sa.ForeignKey('users.id'), nullable=True)

    @declared_attr
    def owned_by(cls):  # pylint: disable=no-self-argument
        """The owned_by user."""
        return relationship("User", foreign_keys=f"[{cls.__name__}.owned_by_id]")
