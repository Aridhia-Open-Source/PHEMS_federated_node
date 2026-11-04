# Pull request ingest and task creation

A merged pull request is stored once per trigger repository, fanned out to the projects that watch it (a trigger per ProjectResource, `UNKNOWN`), evaluated, and becomes a task (`YIELDED`, task `PENDING`) or is rejected (`REJECTED`, final). These cases check the matching rules the end-to-end suites do not: base branch, file type, spec files, datasets, cursors, batching and GitHub. The invalid spec and the unwatched pull request are in [failure paths](failure-paths.md).

Needs: the dev project with all sensors running, and a way to create a branch, a file and a pull request in the trigger repository by hand (the Gitea UI) when a case needs more than `fncli open-pr`. Check the state with `fncli project-show` (see [the index](README.md)).

## A merged pull request on another base branch gets no trigger

1. Note the counts (pull requests, stored, tasks) with the command in [the index](README.md).
2. In Gitea create a branch `qa-other` in the trigger repository. Create a branch off the default branch with a new `.json` spec file under the project resource's `watch_dir`, open a pull request into `qa-other`, merge it.
3. Wait five sensor intervals. Note the counts again.

- **Expected:** the stored count goes up by one; the project's pull request count and task count do not change.
- **Rule:** a project resource gets a trigger only when the pull request's base branch equals the project resource's `base_branch` ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: `nexus/api/tests/test_pull_requests_and_tasks.py` (`test_base_branch_default_override_and_case`, `test_file_matching_against_watch_dir`). No end-to-end group covers a base branch.
- [ ] Pass
- [ ] Fail — notes:

## Only a new `.json` file under `watch_dir` counts

1. Merge a watched pull request first (`fncli open-pr --kind watched --merge`) and let it finish.
2. Open and merge a pull request that edits that same spec file (a modified file, not an added one).
3. Open and merge a pull request that adds a `.md` file under `watch_dir`.
4. Wait five intervals after each merge and compare the counts.

- **Expected:** neither pull request gets a trigger. Both are stored.
- **Rule:** a trigger needs a file the pull request adds, ending in `.json`, under `watch_dir` ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: `nexus/api/tests/test_pull_requests_and_tasks.py` (`test_a_trigger_lists_its_spec_files`, `test_file_matching_against_watch_dir`). No end-to-end group covers a modified file or another extension.
- [ ] Pass
- [ ] Fail — notes:

## Two spec files in one pull request are rejected, naming the files

1. Create one branch, then `fncli commit-gitea-file --branch <b> --kind watched` twice (each commits a new file name), `fncli create-gitea-pr --branch <b> --kind watched`, and `fncli merge-gitea-pr --number <n>`.
2. Watch the pull request in `fncli project-show`.

- **Expected:** the trigger goes `REJECTED` with a `state_cause` that names the files. No task.
- **Rule:** none or several spec files gives `REJECTED` ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]); a `REJECTED` trigger is final ([State transition tables for triggers, tasks and result steps; 409 on a refused move]).
- **Automated by:** Partly automated: `dagster/app/tests/test_pr_parser.py` and `dagster/app/tests/test_evaluate_job.py` (several watched files are rejected, naming them). They miss the live evaluate run.
- [ ] Pass
- [ ] Fail — notes:

## A spec naming a dataset the project cannot use is rejected; one naming none uses the default

1. Commit a spec file under `watch_dir` (in Gitea) shaped like the watched one, `{"spec": {"image": "<same image as the watched spec>", "dataset": "<a name no project has assigned>"}}`, and merge it. Check the field name in [TaskSpec, and a Task derived from spec and trigger].
2. Merge a normal watched pull request (no dataset in the spec).
3. `GET /projects/<pid>/tasks/<id>` for the second task.

- **Expected:** step 1: the trigger is `REJECTED` with a cause; no task. Step 2: a task. Step 3: its spec has the project's default dataset.
- **Rule:** the dataset a spec names must be one assigned to the project and active; with none named the default is used ([TaskSpec, and a Task derived from spec and trigger]).
- **Automated by:** Partly automated: `nexus/api/tests/test_pull_requests_and_tasks.py` (`test_unusable_dataset_rejects_the_pr`, `test_dataset_default_and_case_insensitive_override`). Switching the dataset off is in [enabled and revoked: launch and delivery](enabled-and-revoked-launch-and-delivery.md). They miss the live evaluate run.
- [ ] Pass
- [ ] Fail — notes:

## Editing the spec file after the merge changes nothing

1. `fncli stop-sensor --group evaluate`.
2. `fncli open-pr --kind watched --merge`, and wait until the pull request is stored (`stored_pr_count` up by one, its trigger `UNKNOWN`).
3. In Gitea edit the spec file on the default branch (change the image to another value).
4. `fncli start-sensor --group evaluate`. When the task exists, `GET /projects/<pid>/tasks/<id>`.

- **Expected:** the task's spec is the one at the merge commit, not the edited one.
- **Rule:** the spec is read at the merge commit; editing the file after the merge changes nothing ([TaskSpec, and a Task derived from spec and trigger]).
- **Automated by:** Manual only. The parser tests pass the file as read; no test changes the file between merge and evaluate.
- [ ] Pass
- [ ] Fail — notes:

## A pull request merged before a project was assigned gets no trigger for it

1. `fncli open-pr --kind watched --merge` and wait until it is stored.
2. `fncli second-project-setup QaTwo` (assigns the same GlobalResources, enabled).
3. `fncli project-show --project QaTwo`.
4. `fncli open-pr --kind watched --merge` again.
5. `fncli project-show --project QaTwo`, then `fncli second-project-teardown QaTwo`.

- **Expected:** step 3: no pull requests and no tasks for the new project, although the pull request is stored. Step 5: only the new pull request has a trigger and a task there.
- **Rule:** a new project resource's cursor is the latest stored pull request (or the project resource's creation time); history before it is not replayed ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: `nexus/api/tests/test_pull_requests_and_tasks.py` (`test_cursor_rule_assign_first_then_ingest`, `test_cursor_with_nothing_stored_is_resource_creation_time`). The end-to-end second-project group assigns the resources before it merges.
- [ ] Pass
- [ ] Fail — notes:

## More than 100 merged pull requests behind one cursor are all stored

This is a probe listed in the end-to-end README, not a pass or fail there.

1. `fncli stop-sensor --group ingest`. Note the stored count.
2. Merge 101 pull requests. Use `--kind unwatched` to avoid running 101 tasks (the batching is the same). With `--kind watched` the task count in `fncli project-show` stops at 100 and only `stored` stays reliable; recreate the project afterwards.
3. `fncli start-sensor --group ingest`. Wait.

- **Expected:** the stored count goes up by 101 (the run posts batches of at most 100, oldest first). No pull request is skipped or stored twice.
- **Rule:** ingest posts in batches of 100 and the cursor moves only when a batch is stored ([The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]).
- **Automated by:** Partly automated: `dagster/app/tests/test_ingest_job.py` (batches of at most 100, oldest first) and `nexus/api/tests/test_pull_requests_and_tasks.py` (`test_batch_limit`); they miss a real provider's paging.
- [ ] Pass
- [ ] Fail — notes:

## Repeated sensor ticks never duplicate a pull request or a task

1. After a task has finished, note the counts.
2. Wait ten sensor intervals without merging anything.
3. Note the counts again, and `fncli sensor-status`.

- **Expected:** the counts are unchanged and no tick fails. Posting the same pull requests again changes nothing: the stored numbers come back as `existing`.
- **Rule:** the store is idempotent (unique on repository and number, and on repository, base branch and merge commit) ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: `nexus/api/tests/test_pull_requests_and_tasks.py` (`test_ingest_fans_out_and_is_idempotent`, `test_posting_the_same_pull_request_again_changes_nothing`) and the "nothing happens" waits of the end-to-end failure suite. Restarts are in [sensors, restarts and catch-up](sensors-restarts-and-catch-up.md).
- [ ] Pass
- [ ] Fail — notes:

## One merge commit on two base branches is stored twice and fans out to each

Optional; do it only if you can produce a fast-forward merge to two base branches (check how in your Gitea).

1. `fncli second-project-setup QaTwo`, then `PATCH /projects/<pid>/repositories/triggers/<id>` on it with `{"base_branch": "qa-other"}`. In Gitea create the branch `qa-other` at the same commit as the default branch.
2. Create a branch with a new watched spec file. Open two pull requests from it, one into the default branch and one into `qa-other`, and merge both with fast-forward merges (check how your Gitea does that) so both get the same merge commit.
3. Look at the stored pull requests and each project's triggers (`fncli project-show` and `fncli project-show --project QaTwo`), then `fncli second-project-teardown QaTwo`.

- **Expected:** both pull requests are stored, and each project's resource gets a trigger only for the pull request on its own base branch. A pull request that repeats a merge commit already stored on the same base branch under a new number is skipped (a warning naming both numbers) and does not fail the batch.
- **Rule:** one commit on one base branch belongs to one pull request ([Pull requests stored once per repository, fanned out to project resources, with cursors]).
- **Automated by:** Partly automated: `nexus/api/tests/test_pull_requests_and_tasks.py` (the two tests on a merge commit on two base branches and on a repeated merge commit); they miss a real merge.
- [ ] Pass
- [ ] Fail — notes:

## Ingest, evaluate and delivery work against GitHub

Needs a test repository on GitHub and a token for it. The end-to-end suites use Gitea only.

1. `POST /global/providers` with `type` `github`, `uri` `https://github.com`, `api_uri` `https://api.github.com`. Create a trigger repository and a results repository on test repositories, each with its own Secret, and assign them to a test project.
2. Merge a pull request that adds a spec file under `watch_dir`.
3. Follow it as in [run a task and deliver the result](run-a-task-and-deliver-the-result.md).

- **Expected:** the same states as on Gitea: trigger `UNKNOWN`, `YIELDED`, a task, a results pull request. Ingest uses the list-pulls endpoint (no search rate limit). Errors map the same way as on Gitea.
- **Rule:** both providers give the same results ([GitAPI protocol and GitAPIFactory over Gitea and GitHub]; [Ingest merged pull requests through the pulls endpoint, not search]).
- **Automated by:** Partly automated: `dagster/app/tests/test_github.py`, `dagster/app/tests/test_github_parity.py` (canned responses). No end-to-end test uses GitHub. A pull request whose file list hit the provider's cap (3000 on GitHub) is treated as matching every project resource of the right branch, so its trigger may be rejected at evaluation for having no spec file ([Pull requests stored once per repository, fanned out to project resources, with cursors]); do not try that by hand.
- [ ] Pass
- [ ] Fail — notes:

<!-- link definitions -->
[GitAPI protocol and GitAPIFactory over Gitea and GitHub]: ../decisions/0010-git-api-protocol-and-factory.md
[Ingest merged pull requests through the pulls endpoint, not search]: ../decisions/0012-github-ingest-pulls-endpoint.md
[Pull requests stored once per repository, fanned out to project resources, with cursors]: ../decisions/0011-pull-requests-stored-once-fan-out-and-cursors.md
[State transition tables for triggers, tasks and result steps; 409 on a refused move]: ../decisions/0005-state-transition-tables.md
[TaskSpec, and a Task derived from spec and trigger]: ../decisions/0002-task-spec-and-derivation.md
[The Dagster pipeline: ingest as an op, twelve sensors, one interval, retries]: ../decisions/0014-dagster-pipeline-ops-sensors-and-retries.md
