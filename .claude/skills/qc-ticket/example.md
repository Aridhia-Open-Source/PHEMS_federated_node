<!-- A made-up feature, to show the standard for cluster setup: a ready-to-use file with made-up test data, exact commands, one action and one result per check, and cleaning up after. Never copy its kinds, names or fields: check the real ones in the code. -->
[QC] Quotas set in the cluster limit how many tasks a project runs at once

**PRs:** #1301

### What changed

A project's limit on tasks running at the same time can now be set from the cluster. Tasks over the limit wait until one finishes.

### Before you start

- Needs a project with a trigger repository, and a task file that runs for a few minutes.
- Save this as `qc-quota.yaml`, with your project's name in `project:`:

  ```yaml
  apiVersion: fn.aridhia.com/v1alpha1
  kind: TaskQuota
  metadata:
    name: qc-quota
    namespace: fn-operator
  spec:
    project: <your project's name>
    maxRunning: 1
  ```

### Checks

- [ ] Run `kubectl apply -f qc-quota.yaml`. `kubectl get taskquota qc-quota -n fn-operator` shows it Synced.
- [ ] Merge two task pull requests at once. On the project's Tasks page one task runs and the other waits.
- [ ] When the first task finishes, the second starts.
- [ ] Change `maxRunning` to `2` in the file, apply it again, and merge two more task pull requests. Both run at once.
- [ ] Run `kubectl delete -f qc-quota.yaml`. The project goes back to no limit.
