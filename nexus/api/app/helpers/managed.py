"""
Records the nexus operator manages (ADR 0032). A record its custom resource declares carries managed_by: the operator's
Keycloak user. Its declared fields, and its removal, change only through the custom resource: anyone else's call that
sends one of them is a 409, the same as a refused state move (ADR 0005). Runtime state (revoked, the enabled of a global
resource, cursors, tasks, pull requests, results) stays editable through the API.

A call from the operator marks the record it creates or changes, and so adopts one made by hand.
"""
from http import HTTPStatus

from app.helpers.exceptions import InvalidRequest
from app.helpers.wrappers import Caller

# The fields each custom resource declares, as the API names them
GIT_PROVIDER = {"name", "type", "uri", "api_uri"}
SECRET = {"values"}
REPOSITORY = {"provider_id", "secret_label"}
DATASET = {"name", "host", "port", "type", "read_schema", "write_schema", "secret_label"}
PROJECT = {"enabled", "backfill"}
# A managed project's trigger and results assignments; its dataset assignments are managed only by PUT and DELETE
TRIGGER_ASSIGNMENT = {"watch_dir", "base_branch", "enabled"}
RESULTS_ASSIGNMENT = {"target_dir", "base_branch", "enabled"}


def guard(record, caller: Caller, sent=None, managed: set[str] = frozenset()):
    """
    The operator's call marks the record as its own. Anyone else's is refused with a 409 when the record is managed and
    the call sends one of its managed fields; `sent=None` is a call that is all managed (an assignment or a removal).
    """
    if caller.is_operator:
        record.managed_by = caller.username
        return
    if record.managed_by and (sent is None or set(sent) & managed):
        fields = "" if sent is None else f" ({', '.join(sorted(set(sent) & managed))})"
        raise InvalidRequest(
            f"{type(record).__name__} {record.id} is managed by {record.managed_by}{fields}: "
            "change its custom resource instead",
            code=HTTPStatus.CONFLICT,
        )
