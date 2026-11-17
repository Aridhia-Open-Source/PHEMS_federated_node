"""
A Keycloak identity that has called nexus-api (ADR 0036). Identity only: what a caller may do stays in
Keycloak. Records point at it to say who owns them.
"""
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import declared_attr, relationship
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db


class UserKind(str, Enum):
    """service: the caller is in one of the owner groups (OWNER_GROUPS), a program rather than a person."""
    HUMAN = "human"
    SERVICE = "service"


class User(db.Model, BaseModel):
    """One row per Keycloak identity that has called nexus-api, written by get_caller."""
    __tablename__ = 'users'

    # The Keycloak user id
    id = sa.Column(sa.String(255), primary_key=True)
    username = sa.Column(sa.String(255), nullable=False)
    kind = sa.Column(
        sa.Enum(UserKind, name='userkind', values_callable=lambda kinds: [k.value for k in kinds]),
        nullable=False,
    )
    created_at = sa.Column(sa.DateTime(timezone=False), nullable=False, server_default=func.now())
    last_seen_at = sa.Column(sa.DateTime(timezone=False), nullable=False, server_default=func.now())

    @classmethod
    def seen(cls, user_id: str, username: str, kind: UserKind) -> "User":
        """Creates the user, or refreshes its username, kind and last_seen_at, in one statement, and commits."""
        stmt = insert(cls).values(id=user_id, username=username, kind=kind).on_conflict_do_update(
            index_elements=[cls.id],
            set_={"username": username, "kind": kind, "last_seen_at": func.now()},
        ).returning(cls)
        user = db.session.scalars(
            stmt, execution_options={"populate_existing": True}
        ).one()
        db.session.commit()
        return user

    def __repr__(self):
        return f'<User ({self.username}, {self.kind.value})>'


class OwnedMixin:
    """
    Who owns a record (ADR 0036). owner_id is whoever created it, or the service that last wrote it.
    owner_group, when set, is the Keycloak group or role (one of OWNER_GROUPS) whose members alone may
    change the record; null leaves it open. A model opts in by inheriting this; writes load the record
    through helpers/ownership.get_for_write.
    """
    # The fields the owner group locks: None for the whole record. A model narrows it by overriding.
    owner_locked_fields: frozenset[str] | None = None

    @declared_attr
    def owner_id(cls):  # pylint: disable=no-self-argument
        """The user that created the record, or the service that last wrote it."""
        return sa.Column(sa.String(255), sa.ForeignKey('users.id'), nullable=True)

    @declared_attr
    def owner_group(cls):  # pylint: disable=no-self-argument
        """The group whose members alone may change the record; null when it is open."""
        return sa.Column(sa.String(255), nullable=True)

    @declared_attr
    def owner(cls):  # pylint: disable=no-self-argument
        """The owner_id's user."""
        return relationship("User", foreign_keys=f"[{cls.__name__}.owner_id]")
