# 0012. Pydantic DTO layer for API responses

- Status: Accepted (applied to the models touched so far)

## Context

Response shapes were built ad hoc from models (`sanitized_dict` and similar), which hid fields, mixed timestamp formats and was not testable on its own.

## Decision

- Backend responses are built by pydantic DTOs in `webserver/app/dtos/` on a common `DTO` base (`from_attributes=True`; `from_model` and `dump`). Datetimes serialise through one `WireDatetime` format. Fields that are not plain attributes (e.g. `task_id` of a trigger) are filled by overriding `from_model`.
- DTOs exist for audit, registries, catalogues, dictionaries, projects, secrets, datasets, tasks, trigger and results repositories and results. Task creation goes through `NewTaskDTO.from_spec`, and `TaskSpec` ([0002](0002-task-spec-and-derivation.md)) is a pydantic model too.
- The Dagster code and `fncli` parse the same responses into their own pydantic models (`extra="allow"`, so a new backend field does not break an older client). `fncli` keeps copies on purpose ([0015](0015-fncli-dev-ops-tool.md)).
- `FNFlask` and `sanitized_dict` were dropped.

## Consequences

- One place per response shape; model changes do not leak into the wire format.
- Models and DTOs must both be updated for a new field.
- The DAR and whitelisted-image DTOs were removed while those areas are disconnected ([0014](0014-dar-rename-and-detached-auth.md)).

## Alternatives considered

- **Marshmallow or hand-built dicts**: rejected, pydantic already validates the specs and the Dagster side.
- **Return model dicts directly**: rejected, couples storage to the API.
