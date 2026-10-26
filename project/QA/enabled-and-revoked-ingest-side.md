# Enabled and revoked rules: pull requests and triggers

Two flags sit on a project, on each ProjectResource (a project's resource) and on each GlobalResource and GitProvider. `enabled` is a person's switch; `revoked` is the administrator withdrawing access. A Secret has `enabled` only. This section checks what each flag, at each level, does to new pull requests: does one get stored, does it get a trigger, and what happens to the pull requests merged while something was off when it is switched back on. What the flags do to tasks and results already created is in [enabled and revoked: launch and delivery](enabled-and-revoked-launch-and-delivery.md).

The rules in words:

- A pull request is stored if its trigger repository is polled: the repository is enabled and not revoked, its GitProvider is enabled and not revoked, its Secret is enabled.
- A stored pull request gets a trigger for a project only if the project's resource is active (the project resource, the GlobalResource and the GitProvider all enabled and not revoked), the project is enabled and not revoked, the pull request is after the project resource's cursor, and it matches the project resource's base branch and `watch_dir`.
- Switching something back on (or un-revoking it) moves the cursor of the project resources affected to now. Pull requests merged while it was off are stored but get no trigger: the gap is skipped. The one exception is enabling a disabled project with `backfill`.
- Revoke sets only `revoked` and un-revoke clears only `revoked`; neither changes `enabled`.

The rules are in [docs/architecture/revoke-and-enabled.md], [Enabled, revoked and soft delete] and [Pull requests stored once per repository, fanned out to project resources, with cursors].

Needs: the dev project with all sensors running and no task in flight; an administrator login for anything `--revoked`. Use this routine in every case unless the steps say otherwise:

- **Before:** note the counts (pull requests, stored, tasks) with the command in [the index](README.md).
- **Switch it:** the command in the case.
- **Merge:** `fncli open-pr --kind watched --merge`. Wait five sensor intervals. Note the counts.
- **Switch it back, wait five intervals, note the counts.**
- Wait for each task to finish before the next case.

## A disabled project stores pull requests without a trigger, and enabling it skips them

1. Before. `fncli project-set --enabled false`.
2. Merge.
3. `fncli project-set --enabled true`. Wait five intervals. Counts.
4. Merge another watched pull request.

- **Expected:** after step 2 the stored count is up by one and the project's pull request and task counts are unchanged. After step 3 they are still unchanged: the pull request merged while the project was off never gets a trigger. In step 4 the new pull request gets a trigger and a task.
- **Rule:** a disabled project gets no trigger; enabling it skips the gap by default ([Enabled, revoked and soft delete]; [Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: `webserver/tests/test_pull_requests_and_tasks.py` (`test_a_disabled_project_gets_no_trigger_and_enabling_it_skips_the_gap`) and the stateful test `webserver/tests/test_stateful_rules.py`. The end-to-end failure suite covers the disabled project only with backfill. The unit tests do not run the sensors.
- [ ] Pass
- [ ] Fail — notes:

## Enabling a project with `backfill` creates the missed triggers, once

1. Before. `fncli project-set --enabled false`. Merge. Wait until the stored count is up by one.
2. `fncli project-set --enabled true --backfill`. Wait.
3. `fncli project-set --enabled false`, then `fncli project-set --enabled true --backfill` again.

- **Expected:** after step 2 the pull request merged while the project was off gets a trigger and a task, once (pull request and task counts each up by one). After step 3 there are no more: repeating `backfill` creates no duplicate. Pull requests before the project resource's cursor do not get a trigger.
- **Rule:** `"backfill": true` on enable creates the triggers of pull requests stored while the project was off ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "a PR merged while the project is disabled gets a task when it is enabled with backfill" (written, never run on a cluster); `webserver/tests/test_pull_requests_and_tasks.py` (`test_enabling_with_backfill_twice_creates_no_duplicates`). The suite does not repeat it.
- [ ] Pass
- [ ] Fail — notes:

## `backfill` is refused unless it enables a disabled project

1. On an enabled project: `fncli project-set --enabled true --backfill --expect 400`.
2. On an enabled project: `PATCH /projects/<pid>` with `{"backfill": true}` (no `enabled`).
3. On a disabled project: `PATCH` with `{"enabled": false, "backfill": true}`.

- **Expected:** 400 each time and nothing changes; `backfill` is not stored.
- **Rule:** `backfill` is a 400 unless the body also has `enabled: true` and the project is currently disabled ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Automated: `webserver/tests/test_projects_api.py` (`test_backfill_without_enabling_is_400`, `test_backfill_on_an_enabled_project_is_400`) and the refused-backfill action of the stateful test. They miss the live node.
- [ ] Pass
- [ ] Fail — notes:

## Backfill does not give a trigger to a project resource that is off

1. `fncli project-set --enabled false`. `fncli resource-set trigger --enabled false`.
2. Merge. Wait until stored.
3. `fncli project-set --enabled true --backfill`. Counts.
4. `fncli resource-set trigger --enabled true`. Counts.

- **Expected:** the pull request gets no trigger at step 3 (the project resource is off) and none at step 4 (switching the project resource on skips the gap).
- **Rule:** backfill calls the trigger creation only for project resources that now accept triggers; there is no backfill for any other switch ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: `webserver/tests/test_pull_requests_and_tasks.py` (`test_backfill_leaves_a_resource_that_is_off_without_triggers`); no end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## A revoked project stores pull requests without a trigger, and restoring it skips them

1. Before. `fncli project-set --revoked true`.
2. Merge. Counts.
3. `fncli project-set --revoked false`. Counts after five intervals.
4. Merge another watched pull request.

- **Expected:** step 2: stored up by one, no trigger, no task. Step 3: still none. Step 4: a trigger and a task. The project's `enabled` stayed `true` the whole time.
- **Rule:** a revoked project gets no trigger; un-revoking skips the gap and never changes `enabled` ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "a PR merged while the project is revoked is stored and gets no task" (written, never run on a cluster); `webserver/tests/test_pull_requests_and_tasks.py` (`test_a_revoked_project_gets_no_trigger_and_re_granting_it_skips_the_gap`). The unit tests miss the live sensors, and the suite itself is unproven on a cluster.
- [ ] Pass
- [ ] Fail — notes:

## A trigger resource switched off gets no trigger, and switching it on skips the gap

1. Before. `fncli resource-set trigger --enabled false`. `fncli project-show` (project resource `active` false).
2. Merge. Counts.
3. `fncli resource-set trigger --enabled true`. Counts.
4. Merge another.

- **Expected:** step 2: no trigger and no task, and the pull request is still stored (the poll serves every project). Step 3: still none. Step 4: a trigger and a task.
- **Rule:** switching a project resource back on moves its cursor to now ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "a PR merged while the trigger resource is switched off gets no task" (written, never run on a cluster); `webserver/tests/test_trigger_repositories_and_resources.py` (`test_switching_a_repository_back_on_skips_the_gap`). The unit tests miss the live sensors, and the suite itself is unproven on a cluster.
- [ ] Pass
- [ ] Fail — notes:

## A revoked trigger resource gets no trigger, and un-revoking skips the gap

1. Before. `fncli resource-set trigger --revoked true`. `fncli project-show` (project resource `active` false).
2. Merge. Counts.
3. `fncli resource-set trigger --revoked false`. Counts.
4. Merge another.

- **Expected:** the same as the previous case. The project resource's `enabled` stays `true`.
- **Rule:** the same as the previous case, for `revoked` ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "a PR merged while the resource is revoked never gets a trigger" (written, never run on a cluster); `webserver/tests/test_pull_requests_and_tasks.py` (`test_unrevoke_skips_the_gap`). The unit tests miss the live sensors, and the suite itself is unproven on a cluster.
- [ ] Pass
- [ ] Fail — notes:

## A trigger repository switched off is not polled, and switching it on skips the gap

1. Before. `fncli global-set trigger --enabled false`. `GET /global/repositories/triggers?pollable=true` (it is not listed).
2. Merge. Wait five intervals. Counts, including the stored count.
3. `fncli global-set trigger --enabled true`. Wait five intervals. Counts.
4. Optionally, while it is off, post a batch to `/global/repositories/triggers/<id>/pull_requests` (any valid body).

- **Expected:** step 2: the pull request is not stored while the repository is off; no trigger, no task. Step 3: the pull request is stored on catch-up (stored up by one) and still gets no trigger or task, in any project. Step 4: 400 (the repository is not active).
- **Rule:** a disabled TriggerRepository is not polled and refuses batches; what was merged meanwhile is ingested when it is back on, with no trigger ([docs/architecture/revoke-and-enabled.md#does-a-new-pull-request-get-a-trigger]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "a PR merged while the GlobalResource is switched off gets no task" (written, never run on a cluster); `webserver/tests/test_pull_requests_and_tasks.py` (`test_disabled_and_unknown_repository_refuse_ingest`) and `webserver/tests/test_trigger_repositories_and_resources.py`. The unit tests miss the live sensors, and the suite itself is unproven on a cluster.
- [ ] Pass
- [ ] Fail — notes:

## A revoked trigger repository stops every project, and restoring it skips the gap

1. Needs the second project: `fncli second-project-setup QaTwo`. Before (both projects).
2. `fncli global-set trigger --revoked true`. `fncli project-show` for both (project resources `active` false).
3. Merge. Counts for both.
4. `fncli global-set trigger --revoked false`. Counts for both after five intervals.
5. `fncli second-project-teardown QaTwo`.

- **Expected:** step 3: no trigger or task in either project. Step 4: still none; the pull request is stored. The GlobalResource's `enabled` stayed `true`.
- **Rule:** GlobalResource flags are read live and apply to every project resource ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "a PR merged while the GlobalResource is revoked gets no task" (one project; written, never run on a cluster); `webserver/tests/test_trigger_repositories_and_resources.py` (`test_a_revoked_trigger_repository_is_not_polled_and_takes_no_pull_requests`). The unit tests miss the live sensors, and the suite itself is unproven on a cluster.
- [ ] Pass
- [ ] Fail — notes:

## A GitProvider switched off or revoked stops the repositories on it

No fncli command changes a GitProvider: use `PATCH /global/providers/<id>` with `{"enabled": false}` and, as an administrator, `{"revoked": true}`.

1. Before. Switch the Gitea provider off. `fncli project-show` (trigger resource `active` false, and the results resource).
2. Merge. Counts. Switch it on. Counts. Merge another. Counts.
3. Repeat with `revoked` true, then false.

- **Expected:** with the provider off or revoked, both repositories on it are inactive: no pull request is polled or stored, no trigger, no task. After switching it back on the pull request merged meanwhile is stored on catch-up with no trigger, and the next one is processed.
- **Rule:** provider flags apply to every repository on it ([Global resources and project resources]; [Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `webserver/tests/test_git_providers.py` (a disabled or revoked provider makes its repositories inactive and unpollable; switching it back on skips the gap). No end-to-end group changes a provider, and no test runs the sensors with one switched off.
- [ ] Pass
- [ ] Fail — notes:

## A trigger repository's Secret switched off stops polling, and the repository stays off after it is switched on

1. Before. `fncli secret-set --entity trigger --enabled false`. `fncli project-show` (project resource `active` false).
2. Merge. Counts.
3. `fncli secret-set --entity trigger --enabled true`. `fncli project-show` (project resource still inactive).
4. `fncli global-set trigger --enabled true`. Counts after five intervals.

- **Expected:** step 2: no trigger or task. Step 3: the repository is still off. Step 4: the project resource is active again; the pull request merged meanwhile gets no trigger.
- **Rule:** disabling a Secret switches off what uses it; enabling it does not switch them back on ([docs/architecture/revoke-and-enabled.md#secrets]). The value move is in [secrets and quarantine](secrets-and-quarantine.md).
- **Automated by:** Partly automated: the end-to-end failure suite, group "a PR merged while the trigger repository's Secret is switched off gets no task" (written, never run on a cluster); `webserver/tests/test_global_resources.py`. The unit tests miss the live sensors, and the suite itself is unproven on a cluster.
- [ ] Pass
- [ ] Fail — notes:

## When two switches are off, switching one on changes nothing

1. Before. `fncli resource-set trigger --enabled false` and `fncli global-set trigger --enabled false`.
2. `fncli global-set trigger --enabled true`. `fncli project-show` (project resource `active` false: the project resource is still off).
3. Merge. Counts.
4. `fncli resource-set trigger --enabled true`. Counts.
5. Merge another.

- **Expected:** step 3: stored, no trigger. Step 4: still none (the gap is skipped from now). Step 5: a trigger and a task. Try the same order with `revoked` on the project resource and `enabled` on the GlobalResource.
- **Rule:** a project resource is active only when every level is on and not revoked ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: the stateful test `webserver/tests/test_stateful_rules.py` explores random orders of the project, project resource and trigger repository flags for one project resource, and checks the model; it does not run the sensors or cover Secret or GitProvider flags.
- [ ] Pass
- [ ] Fail — notes:

## Revoke never changes `enabled`, and un-revoke never switches anything on

1. `fncli resource-set trigger --enabled false`. Then `fncli resource-set trigger --revoked true`, then `fncli resource-set trigger --revoked false`. `fncli project-show` after each.
2. Do the same on the project (`fncli project-set`) and on the trigger repository (`fncli global-set trigger`).
3. Switch each back on.

- **Expected:** after un-revoking, `enabled` is still `false` and the project resource or project is still inactive. The flags never overwrite each other.
- **Rule:** revoking sets only `revoked`, so a re-grant restores the previous state without overriding a manual disable ([Enabled, revoked and soft delete]).
- **Automated by:** Automated: `webserver/tests/test_trigger_repositories_and_resources.py`, `webserver/tests/test_projects_api.py`, `webserver/tests/test_git_providers.py` (`..._leaves_enabled_alone`) and the stateful test. They miss Secret and GitProvider combinations on a live node and the sensors.
- [ ] Pass
- [ ] Fail — notes:

## A project resource created after its GlobalResource was revoked is inactive from the start

1. `fncli global-set trigger --revoked true`.
2. `fncli second-project-setup QaTwo`. `fncli project-show --project QaTwo`.
3. `fncli global-set trigger --revoked false`. `fncli second-project-teardown QaTwo`.

- **Expected:** step 2: the new project's trigger resource exists and shows `active` false. After step 3 it is active.
- **Rule:** GlobalResource flags are read live, so they apply to project resources created later ([docs/architecture/revoke-and-enabled.md#where-each-flag-lives]).
- **Automated by:** Automated: `webserver/tests/test_trigger_repositories_and_resources.py` (`test_a_revoked_global_resource_makes_its_project_resources_inactive_one_created_later_too`). It misses a live node.
- [ ] Pass
- [ ] Fail — notes:

## A pull request merged just before a switch-off, and not yet ingested, is skipped when switched on

This is a known limit; the case records what the node does.

1. `fncli stop-sensor --group ingest`.
2. Merge. Do not let ingest run.
3. `fncli resource-set trigger --enabled false`, then `fncli resource-set trigger --enabled true`.
4. `fncli start-sensor --group ingest`. Wait five intervals. Counts.

- **Expected:** the pull request is stored (stored up by one) and gets no trigger, because switching the project resource on moved its cursor to now. If the beta needs such a pull request to be processed, record it as a finding.
- **Rule:** the open question in [Pull requests stored once per repository, fanned out to project resources, with cursors]: a pull request merged just before a project resource is switched off, and not yet ingested, is skipped when it is switched on.
- **Automated by:** Partly automated: the stateful test `webserver/tests/test_stateful_rules.py` models "every pull request that exists at that moment is stored when ingested but never gets a trigger". It has no real ingest sensor or timing.
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[Enabled, revoked and soft delete]: ../decisions/0008-enabled-revoked-and-soft-delete.md
[Global resources and project resources]: ../decisions/0006-global-resources-and-project-resources.md
[Pull requests stored once per repository, fanned out to project resources, with cursors]: ../decisions/0011-pull-requests-stored-once-fan-out-and-cursors.md
[docs/architecture/revoke-and-enabled.md]: ../../docs/architecture/revoke-and-enabled.md
[docs/architecture/revoke-and-enabled.md#does-a-new-pull-request-get-a-trigger]: ../../docs/architecture/revoke-and-enabled.md#does-a-new-pull-request-get-a-trigger
[docs/architecture/revoke-and-enabled.md#secrets]: ../../docs/architecture/revoke-and-enabled.md#secrets
[docs/architecture/revoke-and-enabled.md#where-each-flag-lives]: ../../docs/architecture/revoke-and-enabled.md#where-each-flag-lives
