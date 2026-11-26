# Granting access

Who may see or change a project or global record (a dataset, git provider, secret, trigger repository or results repository) is a list of **grants** in nexus-api. This page is for the admin who sets that list. For how people sign in, see [Sign-in and roles](./Sign-In-And-Roles).

The design is in [ADR 0037](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0037-cedar-authorization-grants-and-policies.md). The rules that apply to everyone are one reviewed file, `nexus/api/authz/policies.cedar`.


## What a grant is

A grant gives one user or one Keycloak group one relation on one record, optionally until a date. Every call is checked, reads included, and a list shows only what the caller may read.

| Relation | Allows |
|---|---|
| `read` | read the record |
| `assign` | add it to a project, without changing it; read it |
| `execute` | run tasks with it; read it |
| `operate` | turn a project and its parts on or off, and backfill; read it. Not secrets, repository settings or assignments |
| `write` | change or delete it; turn it on or off; revoke it; read it |
| `manage` | everything, plus adding and removing the record's grants |

Normal users get at most `read`, `execute` and `operate` on a project. `write` and `manage` stay with admins.

A project's secrets, repositories and assignments have no grants of their own: every check on them is a check on the project.


## Who can grant

Only a `manage` holder, or the `SuperUser`. A user with `write` cannot give access to others.

Whoever creates a project or global record gets `manage` on it, and is its `owned_by` user. That grant cannot be removed while they own it. Records the operator creates give `manage` to the `/roles/service` group, so admins can read and assign them but not edit them.

Creating a global record or a project needs no grant: the `Administrator` and `Service` roles may. Adding a dataset to a project needs `write` on the project and `assign` on the dataset; admins hold `assign` on every global record.


## Grant access

Each project and global record has the same three routes. Here, for a project:

```sh
# List the grants
curl -sS "$FN/projects/3/grants" "${AUTH[@]}" | jq

# The group /studies/uc1 may read; Bob may run tasks until March
curl -sS -X POST "$FN/projects/3/grants" "${AUTH[@]}" -d '{
  "relation": "read", "subject_type": "group", "subject_id": "/studies/uc1"
}'
curl -sS -X POST "$FN/projects/3/grants" "${AUTH[@]}" -d '{
  "relation": "execute", "subject_type": "user", "subject_id": "<bob-keycloak-user-id>",
  "expires_at": "2027-03-01T00:00:00Z"
}'

# Remove one
curl -sS -X DELETE "$FN/projects/3/grants/17" "${AUTH[@]}"
```

The record paths are `/projects/<id>`, `/global/datasets/<id>`, `/global/providers/<id>`, `/global/secrets/<label>`, `/global/repositories/triggers/<id>` and `/global/repositories/results/<id>`. A duplicate grant is a `409`.

A user's id is their Keycloak user id. Prefer groups: membership is managed in Keycloak, and a grant to a group needs no ids.

Revoking a grant applies at once. Removing someone from a group applies when their token next refreshes, within minutes.


## A refused call

A call the caller has no grant for is a `409` that names the record's `owned_by` user: ask them. Nothing changes.


## When the owner leaves

Only the `SuperUser` can take over a record:

```sh
# Claim it, or give it to a user who has called nexus-api
curl -sS -X PUT "$FN/projects/3/owner" "${AUTH[@]}"
curl -sS -X PUT "$FN/projects/3/owner" "${AUTH[@]}" -d '{"user_id": "<erin-keycloak-user-id>"}'
```

The new owner gets `manage`. The old owner's grant stays until a `manage` holder removes it.


## Not covered by grants yet

Tasks started by a merged pull request are not checked against `execute`: the trigger repository's permissions and the review of the pull request are the gate ([ADR 0037](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0037-cedar-authorization-grants-and-policies.md)). `execute` is checked for tasks asked for through the API.
