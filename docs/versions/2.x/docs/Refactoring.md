# API layout and refactoring

The refactor stack reorganises nexus-api without changing the public resource model. Existing clients should continue to use the routes in the interactive [`/docs`](Using-The-API.md) reference; the change is where the implementation lives and how contributors find it.

## Find an endpoint by URL scope

| URL scope | Router package | Examples |
|---|---|---|
| Authentication | `nexus/api/app/auth_api.py` | `/login`, `/refresh_token` |
| Global resources | `nexus/api/app/globals/` | `/global/datasets`, `/global/providers`, `/global/secrets`, `/global/repositories/...`, `/global/users` |
| Projects and project resources | `nexus/api/app/projects/` | `/projects`, `/projects/{project_id}/datasets`, `/projects/{project_id}/tasks` |
| Health | `nexus/api/app/healthcheck_api.py` and `app/health/` | `/health_check`, `/ready_check`, resource health checks |
| Dagster integration | `nexus/api/app/dagster_api.py` | `/dagster/sensors` |

`app/__init__.py` creates the FastAPI application and registers every router. It also applies the default `can_do_admin` scope; only health probes and token routes are intentionally open. Keep route declarations in their scope router and keep shared behavior in the appropriate package below it.

## Find shared behavior

- `app/clients/` contains outbound clients for Keycloak, Kubernetes, Dagster and secret stores.
- `app/repos/` contains git addresses, short-lived git tokens, repository loops and pull-request fan-out.
- `app/tasks/` contains task configuration, resource limits and task specification handling.
- `app/rules/` contains ownership and state-transition rules.
- `app/database/` contains query helpers, URI construction, the model base and soft-delete behavior.
- `app/health/` contains the checks called by the health routes.
- `app/dtos/` contains response DTOs; `app/models/` contains SQLAlchemy models. Responses still follow [ADR 0016](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0016-pydantic-dto-layer.md).

The old catch-all helper modules and unused methods were removed. Do not recreate them as compatibility shims: add new code beside the area that owns the behavior and update its tests.

## Removed dataset catalogue

Datasets no longer have catalogue or dictionary fields. Those tables, API fields, UI fields and Dagster-side models were removed. Use the dataset's current API schema and the [Datasets](Datasets.md) guide; an old request containing those fields must be updated rather than relying on a server-side catalogue.

## Contributor workflow

1. Start with the URL in the API reference and open the matching router package above.
2. Follow the router to its DTO, model and owning client/repository/rule package.
3. Keep authorization, state transitions and soft-delete behavior in the existing rule/database modules rather than duplicating checks in a router.
4. Run the focused API tests and regenerate `nexus/api/openapi.json` when an API contract changes.

The refactor preserves the resource and state concepts described in [Architecture](Architecture.md), [entities](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/docs/architecture/entities.md), and [revoke and enabled](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/docs/architecture/revoke-and-enabled.md).
