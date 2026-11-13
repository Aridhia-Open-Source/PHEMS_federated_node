# Task Review (v1.3.0+)

Task Review is an optional governance feature that holds task results until an administrator has inspected and explicitly approved them. This is useful for institutions that need to verify results don't inadvertently leak sensitive information before they leave the node.

By default this feature is **disabled** - results are available to the requesting user as soon as the task completes.


## Enabling Task Review

In `values.yaml`:

```yaml
taskReview: true
```

Or at deploy/upgrade time:

```sh
helm upgrade federatednode federated-node/federated-node \
    -f values.yaml \
    --set taskReview=true \
    --namespace federated-node
```


## How it works

When enabled:

1. A researcher submits a task (via API or Task Controller) - this is unchanged
2. The task runs and completes
3. Results are **held** - the researcher cannot retrieve them, and if using the Task Controller, automatic delivery is also paused
4. An administrator reviews the results by calling `GET /tasks/<id>/results` - this returns the results to the admin only
5. The administrator either **approves** or **blocks** the results


## Approving results

Once satisfied the results are safe to release:

```sh
curl --request POST "$FN_HOST/tasks/<task-id>/results/approve" \
    --header "Authorization: Bearer $TOKEN"
```

After approval, the researcher can retrieve results via `GET /tasks/<id>/results`. If using the Task Controller, automatic delivery to the configured destination also proceeds.


## Blocking results

To prevent results from being released (recorded in the audit log):

```sh
curl --request POST "$FN_HOST/tasks/<task-id>/results/block" \
    --header "Authorization: Bearer $TOKEN"
```

Blocking is primarily for audit trail purposes. The FN does not send automatic notifications - if you block results, inform the researcher through your own processes.


## Notes

- Task Review applies regardless of how a task was triggered (direct API call or Task Controller)
- The `cleanupTime` setting still applies - results will be cleaned up after that many days even if not approved, so review promptly
- Results held for review are visible to administrators only via `GET /tasks/<id>/results`
