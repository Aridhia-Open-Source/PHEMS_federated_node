# Two projects on the same GlobalResources

A trigger repository is polled once and each pull request is stored once, however many projects assign it. Each project keeps its own project resource, flags, cursor, triggers, tasks and results. The GlobalResources (Secret, dataset, repositories) are shared, so an edit to one reaches both projects. These cases check that the two projects stay independent where they should and move together where they must.

Needs: the dev project (called here "the first project") and a second project from `fncli second-project-setup QaTwo` (it has the same Secrets, dataset, trigger repository and results repository assigned, with the same settings, and is enabled). Look at either with `fncli project-show` and `fncli project-show --project QaTwo`. `fncli second-project-teardown QaTwo` removes the second project and leaves the GlobalResources. For a third project use the name `QaThree`.

## One pull request gives each project its own trigger and task

1. `fncli second-project-setup QaTwo`.
2. `fncli open-pr --kind watched --merge`.
3. Look at both projects until both tasks finish.

- **Expected:** the pull request is stored once (`stored_pr_count` is 1 higher in both views). Each project has its own trigger `YIELDED` and its own task; the task ids differ. Each task delivers its own result (branches differ because they carry the task id).
- **Rule:** pull requests are stored once and fanned out, a trigger per project resource ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: the end-to-end failure suite, group "a second project on the same repository" (`dagster/fncli/tests/e2e/test_failure_paths.py`, written, never run on a cluster); `webserver/tests/test_pull_requests_and_tasks.py` (`test_two_projects_on_one_repo_are_independent`). It checks the two tasks, not that both results land in the one results repository.
- [ ] Pass
- [ ] Fail — notes:

## Revoking one project's resource leaves the other project working

1. With both projects set up: `fncli resource-set trigger --revoked true --project QaTwo`.
2. Let tasks finish, note both projects' counts, merge a watched pull request.
3. `fncli resource-set trigger --revoked false --project QaTwo` when done.

- **Expected:** the first project gets the pull request, a trigger and a task. `QaTwo` gets nothing (its project resource is inactive). The pull request is stored once.
- **Rule:** the project resource is the permission boundary; revoking it stops only that connection ([Global resources and project resources]).
- **Automated by:** Partly automated: the same end-to-end group (revokes the second project's resource); `webserver/tests/test_trigger_repositories_and_resources.py` (`test_two_projects_assign_one_repo_independently`). It does not un-revoke and check the gap on the second project.
- [ ] Pass
- [ ] Fail — notes:

## Switching a GlobalResource off stops both; switching a project resource off stops one

1. `fncli resource-set trigger --enabled false --project QaTwo`. Merge a watched pull request. Compare the two projects.
2. `fncli resource-set trigger --enabled true --project QaTwo`.
3. `fncli global-set trigger --enabled false`. Merge a watched pull request. Compare.
4. `fncli global-set trigger --enabled true`. Compare after five intervals.

- **Expected:** step 1: only the first project gets a task. Step 3: neither project gets a trigger, and the pull request is not stored while the repository is off. Step 4: the pull request merged during step 3 is stored on catch-up, and neither project gets a trigger for it (the gap is skipped for both).
- **Rule:** GlobalResource flags are read live and apply to every project resource; a project resource's flags apply to that project ([Enabled, revoked and soft delete]).
- **Automated by:** Partly automated: `webserver/tests/test_trigger_repositories_and_resources.py`, `webserver/tests/test_git_providers.py`. The end-to-end suite switches the GlobalResource off for one project only.
- [ ] Pass
- [ ] Fail — notes:

## A project with a different `watch_dir` matches different pull requests

1. `PATCH /projects/<pid>/repositories/triggers/<id>` on `QaTwo` with a different `watch_dir` (for example `triggers2`).
2. Merge a watched pull request that adds a file under the first project's `watch_dir` only, then one under `triggers2` only (commit the file by hand in Gitea).

- **Expected:** each pull request gets a trigger and a task only in the project whose `watch_dir` holds the file. Both are stored once.
- **Rule:** each project resource matches on its own `base_branch` and `watch_dir` ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: `webserver/tests/test_pull_requests_and_tasks.py` (`test_file_matching_against_watch_dir`, `test_two_projects_on_one_repo_are_independent`); no end-to-end group.
- [ ] Pass
- [ ] Fail — notes:

## Editing a shared dataset or results repository hits the tasks of both projects

Do this with the launcher stopped (see "Make a change while a task is still PENDING" in [the index](README.md)).

1. Stop the launcher. Merge a watched pull request. Wait until both projects have a `PENDING` task.
2. Change a field that is pinned, once, for the shared dataset (`PATCH /global/datasets/<id>`, for example `host` to another value).
3. Start the launcher. Put the field back afterwards.

- **Expected:** both tasks go `FAILED` at launch, each with a cause that names the change. Neither runs.
- **Rule:** editing a GlobalResource affects every project assigned to it; a task whose pinned configuration changed fails ([A task is pinned to its configuration]).
- **Automated by:** Partly automated: `webserver/tests/test_task_config.py` (one project's task). No test uses two projects.
- [ ] Pass
- [ ] Fail — notes:

## Both projects deliver into the same results repository without clashing

1. With both set up, merge a watched pull request. Wait for both results.
2. In Gitea, list the branches and pull requests of the results repository.
3. Merge both results pull requests with `fncli merge-results-pr --number <n>` for each.

- **Expected:** two branches, each ending `<task id>-<first 7 of the merge sha>` with different task ids, and two results pull requests, one per task. Both results reach `MERGED`. Neither delivery overwrote the other.
- **Rule:** the delivery branch carries the task id; a results repository may be shared by projects ([Results delivered as a pushed branch plus a results pull request]).
- **Automated by:** Partly automated: `dagster/app/tests/test_results_delivery.py` (the layout, one task); the end-to-end failure group lets both projects' tasks finish (and waits for results to settle), but asserts nothing about the shared results repository.
- [ ] Pass
- [ ] Fail — notes:

## Deleting one project leaves the other and the GlobalResources

1. With both projects set up and a finished task in each, `fncli second-project-teardown QaTwo`.
2. `fncli project-show`, `GET /global/repositories/triggers`, `GET /global/datasets`.
3. Merge another watched pull request.

- **Expected:** the first project is unchanged and still gets the next pull request. The deleted project is hidden (404) with its project resources; its pull requests' triggers are hidden, the stored pull requests remain. The GlobalResources and their Secrets are untouched.
- **Rule:** deleting a project soft-deletes it and its project resources only; it does not touch Secrets, datasets or repositories ([Global resources and project resources]).
- **Automated by:** Partly automated: `webserver/tests/test_projects_api.py` (`test_delete_cascades_project_resources_but_keeps_global_resources`, `test_delete_hides_the_projects_pr_triggers_but_keeps_global_prs`); the end-to-end failure group tears the second project down. The task-in-flight side is in [enabled and revoked: launch and delivery](enabled-and-revoked-launch-and-delivery.md). They miss tasks in flight.
- [ ] Pass
- [ ] Fail — notes:

## Three projects on one repository

1. `fncli second-project-setup QaTwo` and `fncli second-project-setup QaThree`.
2. Merge three watched pull requests, one after the other, without waiting.
3. When everything has settled, count tasks and results per project.

- **Expected:** each project has three triggers and three tasks, each task belongs to one project, there are nine results in total and no duplicate task for any project and pull request. The pull requests are stored once each.
- **Rule:** one trigger per project resource and pull request; one task per trigger ([Polymorphic Trigger with PullRequestTrigger and ApiRequestTrigger]; [Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Manual only. The unit tests use at most two projects; the end-to-end suites use two with one pull request at a time.
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[A task is pinned to its configuration]: ../decisions/0009-task-pinned-to-its-configuration.md
[Enabled, revoked and soft delete]: ../decisions/0008-enabled-revoked-and-soft-delete.md
[Global resources and project resources]: ../decisions/0006-global-resources-and-project-resources.md
[Polymorphic Trigger with PullRequestTrigger and ApiRequestTrigger]: ../decisions/0001-polymorphic-triggers.md
[Pull requests stored once per repository, fanned out to project resources, with cursors]: ../decisions/0011-pull-requests-stored-once-fan-out-and-cursors.md
[Results delivered as a pushed branch plus a results pull request]: ../decisions/0013-results-delivered-as-branch-and-pull-request.md
