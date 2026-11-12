# Using the API

This guide covers everyday interactions with the nexus-api of a Federated Node 2.x: logging in, what the routes are for, and the conventions they share. A researcher does not need the API to run a task: see the [Researcher guide](./Researcher-Guide).

Every node serves its own interactive reference at `/docs`, for example `https://fn.your-institution.example.com/docs`, and the same description as `openapi.json` (also in the repo's [nexus/api](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/tree/beta/nexus/api) folder). Treat those as the source of truth for request and response bodies.


## Setup

```sh
export FN=https://fn.your-institution.example.com
```


## Authentication

### Login

`/login` takes form fields, not JSON, and returns a bearer token:

```sh
TOKEN=$(curl --silent "$FN/login" \
    -F "username=your@email.com" \
    -F "password=yourpassword" | jq -r '.token')

AUTH=(-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")
```

Tokens are valid for 8 hours by default (the chart value `token.life`).

### Refresh a token

```sh
curl --silent -X POST "$FN/refresh_token" "${AUTH[@]}"
```


## The routes

| Area | Routes | Who |
|---|---|---|
| Health | `GET /health_check`, `GET /ready_check` | No login needed |
| Login | `POST /login`, `POST /refresh_token` | Anyone with an account |
| Global resources | `/global/secrets`, `/global/providers`, `/global/datasets`, `/global/repositories/triggers`, `/global/repositories/results` | Admin to create, change and revoke |
| Users | `/global/users` | Admin |
| Projects | `/projects`, `/projects/<id>` | Admin to create |
| Assignments | `/projects/<id>/datasets`, `.../secrets`, `.../repositories/triggers`, `.../repositories/results` | Admin |
| Tasks and results | `/projects/<id>/tasks`, `/projects/<id>/results` | Task rights. `GET /tasks` (every task) is admin |
| Sensors | `/dagster/sensors` | Admin |
| Health checks | `GET .../healthcheck` on the node, a project, and each resource | Admin |

The pattern for each kind of resource is the same: `GET` lists or reads, `POST` creates (globals), `PUT` assigns (to a project), `PATCH` changes, `DELETE` removes. The id in the URL of an assignment is the **global resource's id**, not the assignment's.


## Conventions

- **Enabled and revoked.** Every resource has an `enabled` flag, which anyone allowed to manage it can flip, and a `revoked` flag, which is admin only and takes effect at once. Only a resource that is enabled and not revoked is used. See [Operations](./Operations#switch-things-on-and-off).
- **Soft delete.** `DELETE` hides the record and frees its name. A resource that projects still use gives a `409` that lists them.
- **Health checks.** A failing check is reported in the response body with a status of 200, never a 500, and never contains a secret value.
- **Secrets are write-only.** No call returns a secret's values or even its key names.
- **Unknown fields.** Some create bodies (a dataset, for example) ignore fields they do not know, so read a record back after creating it.
- **Bad input.** An invalid request body is a `400`. A move a record's state does not allow is a `409`.


## Users

Logins are Keycloak users. An admin creates and lists them through the API:

```sh
# Create a user. The response shows a temporary password, once.
curl -sS -X POST "$FN/global/users" "${AUTH[@]}" -d '{
  "email": "researcher@your-institution.example.com",
  "firstName": "Ada",
  "lastName": "Researcher",
  "role": "Users"
}' | jq

# List users, with their roles and whether they still have to set a password
curl -sS "$FN/global/users" "${AUTH[@]}" | jq
```

Only `email` is required. `username` defaults to the email, and `role` to `Users`. A user that already exists is a `400`.

The new user changes the temporary password with `PUT /global/users/reset-password` and the body `{"email": "...", "tempPassword": "...", "newPassword": "..."}`, which needs no login.

The node's roles are realm roles in Keycloak:

| Role | Used for |
|---|---|
| `Users` | A basic login. Researchers do not need one in the common case: they work in git. |
| `Administrator` | Registers and revokes the global resources, creates users, and manages projects. |
| `Super Administrator` | Everything an `Administrator` can do, plus the wider Keycloak realm permissions. |
| `System` | Integrations. Dagster logs in to nexus-api as a system user. |

The first admin is created at install time from `firstUserSecret` ([Deploy: Core](./Deploy-Core#3-create-the-namespace-and-the-secrets-you-must-provide)).


## Datasets, repositories, projects

These are covered where you set them up:

- Dataset fields and checks: [Datasets](./Datasets).
- Switching things on and off: [Operations](./Operations#switch-things-on-and-off).


## Tasks

A task is normally created by a merged pull request, so there is no "submit" call to learn: see [Researcher guide](./Researcher-Guide). Through the API you look at tasks and manage them (admin):

```sh
# The tasks of a project, with their status
curl -sS "$FN/projects/$PROJECT_ID/tasks" "${AUTH[@]}" | jq

# One task
curl -sS "$FN/projects/$PROJECT_ID/tasks/$TASK_ID" "${AUTH[@]}" | jq

# The pull request that created it
curl -sS "$FN/projects/$PROJECT_ID/tasks/$TASK_ID/trigger" "${AUTH[@]}" | jq

# Its results delivery
curl -sS "$FN/projects/$PROJECT_ID/tasks/$TASK_ID/results" "${AUTH[@]}" | jq

# Queue a failed or canceled task for another attempt
curl -sS -X POST "$FN/projects/$PROJECT_ID/tasks/$TASK_ID/retry" "${AUTH[@]}" | jq
```

A task's status is `PENDING`, `QUEUED`, `RUNNING`, `SUCCESS`, `FAILED` or `CANCELED`. The reason a task cannot start or a pull request was rejected is in `state_cause`.

Some routes in the reference are placeholders that answer "not implemented" in the beta: cancelling a task, reading its logs, and approving or blocking its results. Read a run's logs in the Dagster UI ([Operations](./Operations#reading-a-run)).

`POST /projects/<id>/tasks` creates a task without a pull request, but results delivery is built around the pull request, so such a task has no results delivery. Use a pull request.


## Sensors

Nothing runs until the Dagster sensors are started. As an admin, start and stop them from the API:

```sh
# Start every sensor
curl -sS -X PATCH "$FN/dagster/sensors" "${AUTH[@]}" -d '{"status": "RUNNING"}' | jq

# Stop one
curl -sS -X PATCH "$FN/dagster/sensors/task_launcher_sensor" "${AUTH[@]}" -d '{"status": "STOPPED"}' | jq
```

`GET /dagster/sensors` lists each sensor with its status and its latest tick. See [Operations](./Operations#start-the-sensors).
