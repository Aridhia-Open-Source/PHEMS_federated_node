# Auth stack review (Claude)

Findings per PR. Format: file:line - issue - fix - comment.

## #685 cedar write enforcement

- `nexus/api/app/datasets_api.py:115` - `?force=true` delete soft-deletes every project's assignment but only checks `write` on the dataset, not on those projects (ADR 0037: cascades check every record). Same for trigger/results repository and secret deletes. - Require `write` on each assignment's project before `delete_global`. - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/685#discussion_r4674988767
- `nexus/api/app/tasks_api.py:215` - Retry/cancel need project `write` (admins only), so users with `execute` cannot retry or cancel their own tasks; retry skips the dataset `execute` re-check. - Check `execute` on the project and the task's dataset. - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/685#discussion_r4674988776
  - Note: #688 adds `require_each` on the force deletes, which fixes the first #685 finding further up the stack.

## #688 cedar read enforcement

- No findings.

## #686 keycloak token verification

- `nexus/api/app/clients/access_token.py:37` - `azp` must equal the `global` client, so client-credentials tokens of the operator and Dagster clients (ADR 0035/0036) are refused with 401. - Accept a configured list of client ids. - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/686#discussion_r4674997502

## #683 keycloak roles and accounts

- `k8s/federated-node/scripts/realms.json:116` - `Administrator` keeps realm-management `manage-users`/`manage-clients`/`manage-authorization`: an admin can join `/roles/superuser` through the Keycloak admin API and read the `global` client secret (breaks ADR 0036). - Drop the `manage-*` roles from Administrator. - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/683#discussion_r4675000185

## #684 grants DB and API

- No findings.

## #687 cedar setup

- `nexus/api/authz/policies.cedar:47` - ADR 0037 keeps `write`/`manage` with admins, but nothing stops a manage holder granting `manage` to a `Users` account or group, who can then change the record and grant further. - Add a forbid on `write`/`manage` for `Role::"Users"` (or refuse such grants in `post_grant`). - https://github.com/Aridhia-Open-Source/PHEMS_federated_node/pull/687#discussion_r4675008699

## #682 owner group removal

- No findings.

## #733 roles.yaml permissions

- Not reviewed: the PR has no changes yet (only a merge commit; +0 -0). The code still uses `Group::"/roles/admins"` / `Role::"SuperUser"` rules, not ADR 0037's `roles.yaml` permissions and `@id` names.
