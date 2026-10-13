# 0014. DAR rename; Keycloak and whitelisted images detached

- Status: Provisional (disconnected until the authorization rework)

## Context

"Request" was the name of the Data Access Request model, but the new model needs it: a task is requested through an `ApiRequestTrigger`. Authorization (Keycloak resources, per-DAR clients, token exchange) is being reworked by another effort and the old coupling blocked the task work.

## Decision

- Rename the Data Access Request model, table and API to **DAR** (`models/extras/dar.py`, `dar_api.py`, table `dars`). Freed names: `ApiRequestTrigger`, `api_request_triggers`.
- Disconnect, with `TODO(DAR)`, `TODO(whitelisted_images)` and `TODO(auth)` markers: `dar_api` and `whitelisted_images_api` blueprints are not registered; DAR checking and per-DAR token exchange in `@auth` are bypassed (every caller takes the plain path); Keycloak calls from dataset create/delete/rename are detached; the DAR and whitelisted-image DTOs and the token-transfer tests are skipped or removed.
- The Dagster side still authenticates to the backend with a Keycloak system user (`DAGSTER_KC_USER`); the git token read in delivery is marked `TODO(auth)`.

## Consequences

- Dataset and task endpoints work without DAR bookkeeping, so the trigger/task pipeline can be built and tested.
- Access control for non-admin callers is weaker than before until the rework; do not treat the current `@auth` as the final design.
- Re-attaching is by the TODO markers and git history (the removed DTOs are restorable).

## Alternatives considered

- **Port DAR to the new model now**: out of scope, the authorization design is being changed elsewhere.
- **Delete DAR**: rejected, it is expected to return.
