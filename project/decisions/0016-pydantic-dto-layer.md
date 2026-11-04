# 0016. Pydantic DTO layer for API responses

## Context

Response shapes built ad hoc from models hide fields, mix timestamp formats and cannot be tested on their own.

## Decision

- Backend responses are built by pydantic DTOs in `nexus/api/app/dtos/` on a common `DTO` base (`from_attributes=True`; `from_model` and `dump`; `page_of` for paged lists). Datetimes serialise through one `WireDatetime` format. Fields that are not plain attributes (for example `task_id` of a trigger, `pr_count` of a trigger resource) are filled by overriding `from_model`.
- DTOs exist for audit, registries, git providers, datasets, projects, secrets, tasks and task specs, trigger and results repositories, results, healthchecks and sensors. Task creation goes through `NewTaskDTO.from_spec`, and `TaskSpecRequest` ([0002](0002-task-spec-and-derivation.md)) is a pydantic model too.
- The Dagster code and `fncli` parse the same responses into their own pydantic models (`extra="allow"`, so a new backend field does not break an older client). `fncli` imports them from `dagster/app` ([0018](0018-fncli-dev-ops-tool.md)).
- The DAR and whitelisted-image areas have no DTOs while they are disconnected ([0017](0017-authorization-detached-from-dar-and-keycloak.md)).

## Consequences

- One place per response shape; model changes do not leak into the wire format.
- Models and DTOs must both be updated for a new field.
- A shape change across nexus-api, Dagster and fncli shows up only in tests that parse the same responses.

## Alternatives considered

- **Marshmallow or hand-built dicts:** pydantic already validates the specs and the Dagster side.
- **Return model dicts directly:** couples storage to the API.
