# Handover notes

Plans and notes that are not decision records. The decision records in [project/decisions](../decisions/README.md) win where they differ. The index of all docs is [docs/README.md](../../docs/README.md).

## Things decided and not to relitigate

- Webhooks from GitHub straight into the node: rejected, the node stays outbound-only.
- Argo CD for mirroring: rejected, it sees git refs and no pull request objects.
- One mirror per project (a Gitea org per project): only the fallback if the GlobalResource model is not done.
- A `disabled_reason` string: rejected in favour of the `revoked` boolean.
- Real-time updates were never a requirement.
- A flat compatibility API (assignment id as `id`): dropped. Cross-project loops are forbidden and revoke is immediate (ADR [0019](../decisions/0019-global-resources-and-shared-pull-requests.md), section 11).
