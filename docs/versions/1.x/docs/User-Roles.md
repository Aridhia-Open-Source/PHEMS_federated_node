# User Roles and Permissions

The Federated Node uses Role-Based Access Control (RBAC) managed through Keycloak.


## Roles

| Role | Typical use |
|---|---|
| **Super Administrator** | Full access to everything |
| **Administrator** | Full access to everything (same as Super Admin via the FN API) |
| **System** | Service accounts and automation - full task/dataset access, no user management |
| **User** | Researchers - limited by default, permissions granted per-dataset |


## Permissions by role

| Permission | Super Admin | Admin | System | User |
|---|---|---|---|---|
| `can_admin_dataset` | ✅ | ✅ | ✅ | ❌ |
| `can_exec_task` | ✅ | ✅ | ✅ | Dataset grant only |
| `can_admin_task` | ✅ | ✅ | ✅ | Dataset grant only |
| `can_access_dataset` | ✅ | ✅ | ✅ | ❌ |
| `can_transfer_token` | ✅ | ✅ | ✅ | Dataset grant only |
| `can_do_admin` | ✅ | ✅ | ❌ | ✅ |
| `can_send_request` | ✅ | ✅ | ✅ | ❌ |
| `can_admin_request` | ✅ | ✅ | ✅ | ❌ |


## Permission descriptions

| Permission | Description |
|---|---|
| `can_admin_dataset` | Create, edit, and delete dataset mappings |
| `can_exec_task` | Submit a task to run against a dataset |
| `can_admin_task` | View task logs and cancel running tasks |
| `can_access_dataset` | View dataset connection metadata (not the underlying data) |
| `can_transfer_token` | Retrieve an access token after dataset access is granted |
| `can_do_admin` | Access audit logs, the service-info endpoint, and create/list FN users |
| `can_send_request` | Submit a data access request for a dataset |
| `can_admin_request` | Manage data access requests (currently inactive) |


## Granting users access to datasets

A `User` cannot run tasks until an administrator grants them access to a specific dataset via the `token_transfer` endpoint. After this grant they receive `can_exec_task`, `can_admin_task`, and `can_transfer_token` scoped to that dataset only.

See [Using the API](Using-The-API.md) for the `token_transfer` API call.


## Creating users

```sh
curl --location "$FN_HOST/users/" \
    --header 'Content-Type: application/json' \
    --header "Authorization: Bearer $TOKEN" \
    --data '{
        "email": "researcher@institution.com",
        "role": "User"
    }'
```

If the user doesn't already exist in Keycloak they are created automatically. Administrator accounts must be configured via `firstUserSecret` at deploy time or directly in Keycloak - they cannot be created through the FN API.
