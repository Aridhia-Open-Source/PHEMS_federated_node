"""Grants on projects and global records (ADR 0037), as listed and as requested."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.dtos.base import DTO, WireDatetime
from app.models.grant import RELATIONS, SUBJECT_TYPES, Grant


class GrantDTO(DTO):
    """One grant on a record (ADR 0037). subject_id is a Keycloak user id or group path; created_by a user id."""
    id: int
    relation: str
    subject_type: str
    subject_id: str
    expires_at: WireDatetime | None
    created_by: str | None
    created_at: WireDatetime

    @classmethod
    def from_model(cls, obj: Grant):
        return cls(
            id=obj.id, relation=obj.relation, subject_type=obj.subject_type, subject_id=obj.subject_id,
            expires_at=obj.expires_at, created_by=obj.created_by_id, created_at=obj.created_at,
        )


class GrantRequest(BaseModel):
    """A grant to add. With no expires_at it never expires."""
    model_config = ConfigDict(extra="forbid")

    relation: Literal[RELATIONS]
    subject_type: Literal[SUBJECT_TYPES]
    subject_id: str = Field(min_length=1, max_length=255)
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def naive_utc(cls, value: datetime | None) -> datetime | None:
        """Stored without a time zone, as UTC, like every other timestamp; a naive value is taken as UTC."""
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value


class OwnerRequest(BaseModel):
    """The new owner: a nexus-api user id. Leave it out to claim the record for the caller."""
    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, min_length=1, max_length=255)
