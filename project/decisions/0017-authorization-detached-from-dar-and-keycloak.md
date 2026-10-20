# 0017. Authorization detached from DAR, Keycloak and whitelisted images

## Context

Authorization (Keycloak resources, per-DAR clients, token exchange) is designed separately from the task pipeline, and coupling the pipeline to it would block running and testing the pipeline. The name "request" belongs to the new trigger model: a task is requested through an `ApiRequestTrigger` ([0001](0001-polymorphic-triggers.md)), so the Data Access Request model is called **DAR**.

## Decision

- The Data Access Request model, table and API are named DAR (`models/extras/dar.py`, `dar_api.py`, table `dars`). The names `ApiRequestTrigger` and `api_request_triggers` belong to the trigger.
- DAR and whitelisted images are disconnected, with `TODO(DAR)`, `TODO(whitelisted_images)` and `TODO(auth)` markers:
  - the `dar_api` and `whitelisted_images_api` blueprints are not registered;
  - DAR checking and per-DAR token exchange in `@auth` are bypassed, so every caller takes the plain path (admin scope or the endpoint's scope);
  - Keycloak calls from dataset create, delete and rename are detached;
  - the DAR and whitelisted-image DTOs do not exist.
- Dataset-level authorisation is not part of the dataset design ([0006](0006-global-resources-and-project-links.md)).
- The Dagster side authenticates to the backend with a Keycloak system user (`DAGSTER_KC_USER`); the git token read in delivery is marked `TODO(auth)` ([0007](0007-secrets-and-secret-providers.md)).
- Creating global resources, and the `revoked` flag, need the admin role ([0006](0006-global-resources-and-project-links.md), [0008](0008-enabled-revoked-and-soft-delete.md)).

## Consequences

- Dataset and task endpoints work without DAR bookkeeping, so the trigger and task pipeline can be run and tested.
- Access control for non-admin callers is weaker than the DAR design: the current `@auth` is not the final design.
- Re-attaching DAR or whitelisted images starts from the TODO markers.

## Alternatives considered

- **Port DAR to the new model now:** the authorization design is being changed elsewhere.
- **Delete DAR:** it is expected to return.

## Open questions

- The role model for user, admin and system tiers ([auth-mvp-plan.md](../auth-mvp-plan.md)).
- Whether `whitelisted_images` follows the global pattern.
