"""
Soft delete: a deleted row keeps existing but the API treats it as gone. Every ORM query and
every collection loaded through a relationship hides rows with `deleted_at` set; an internal or
audit read opts out with `.execution_options(include_deleted=True)`. Following a many-to-one
reference (task.project, resource.results_repository, result.assignment) still loads a deleted row,
so history never meets None. A row that has `revoked` (a project resource, a global resource, a project) also gets it,
since deleting something withdraws everything under it.
"""
from datetime import datetime as dt
from datetime import timezone as tz
from http import HTTPStatus

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from app.helpers.base_model import db
from app.helpers.exceptions import InvalidRequest


class SoftDeleteMixin:
    deleted_at = sa.Column(sa.DateTime, nullable=True)

    def soft_delete(self):
        """Marks the row deleted, and revoked if it has the flag. Leaves the commit to the caller."""
        self.deleted_at = dt.now(tz=tz.utc).replace(tzinfo=None)
        if hasattr(self, 'revoked'):
            self.revoked = True


def delete_global(resource, project_resources: list, force: bool) -> None:
    """
    Soft deletes a global resource (a dataset or a repository). While projects have it assigned that is a
    409 naming them, unless the request has ?force=true, which soft deletes every project's resource for it too.
    """
    if project_resources and not force:
        error = InvalidRequest(
            f"{resource!r} is assigned to {len(project_resources)} project(s): delete with ?force=true to unassign them",
            HTTPStatus.CONFLICT,
        )
        error.extra_fields = [{"id": project_resource.project.id, "name": project_resource.project.name} for project_resource in project_resources]
        raise error
    for project_resource in project_resources:
        project_resource.soft_delete()
    resource.soft_delete()
    db.session.commit()


@event.listens_for(Session, "do_orm_execute")
def hide_deleted(state):
    if not state.is_select or state.is_column_load or state.execution_options.get("include_deleted", False):
        return
    if state.is_relationship_load and not state.loader_strategy_path.path[-1].uselist:
        return
    # Not propagated to the lazy loads of the objects it loads: each of them gets its own decision above
    state.statement = state.statement.options(
        with_loader_criteria(
            SoftDeleteMixin, lambda cls: cls.deleted_at.is_(None), include_aliases=True, propagate_to_loaders=False
        )
    )
