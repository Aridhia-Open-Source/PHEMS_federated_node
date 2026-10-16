# Stage m0 spike: Gitea mirror feasibility (ADR 0020)

**Result: GO**, with one required design change to the sync loop (see "Surprises", item 1).

Setup: `gitea/gitea:28.1.0` (the tag in `k8s/federated-node/values.yaml`), sqlite, in Docker as `gitea-spike-m0` on `127.0.0.1:3917`. Source: public `backstage/mkdocs-monorepo-plugin` (66 closed PRs), read with no GitHub token: one REST call (`/pulls?state=closed`) plus `git clone --mirror` and a `refs/pull/*/head` fetch. Scripts are in `spike/` (`00_prepare.sh` ... `05_pullmirror.sh`); responses below are trimmed from real runs.

Merge styles available upstream and tested (classified from `merge_commit_sha` in the cloned repo):

| Style | Shape | PR tested |
|---|---|---|
| Merge commit | 2 parents, PR head is an ancestor of the merge commit | #126 |
| Squash | 1 parent, PR head is not an ancestor, merge commit subject ends `(#n)` | #140, #109 |
| Fast-forward / rebase of a single commit | 1 parent, merge commit == PR head | #97 |
| Rebase with rewritten SHAs | none found in the 50 merged PRs, so not tested (it has the same shape as squash: head not an ancestor) | |

## Sync steps proven (all worked)

```
docker exec -u git gitea-spike-m0 gitea admin user create --admin --username spikeadmin ... --must-change-password=false
docker exec -u git gitea-spike-m0 gitea admin user generate-access-token --username spikeadmin --scopes all --raw   # token, not printed
POST /api/v1/orgs                     {"username":"spike-org","visibility":"private"}                  -> 201
POST /api/v1/orgs/spike-org/repos     {"name":"mirror-test","auto_init":false,"private":true,...}      -> 201
git -c http.extraHeader="Authorization: token $T" push <gitea> 'refs/heads/*:refs/heads/*'              -> master, agentbellnorm-patch-2 pushed as-is
git -c http.extraHeader=... push <gitea> 'refs/pull/*/head:refs/heads/pr/*'                           -> 72 [new branch] pr/<n>
POST /api/v1/admin/users              {"username":"davidxia","email":"davidxia@shadow.invalid","password":...,"must_change_password":false}   -> 201
PUT  /api/v1/repos/spike-org/mirror-test/collaborators/davidxia   {"permission":"write"}              -> 204
POST /api/v1/repos/spike-org/mirror-test/pulls   (Sudo: davidxia) {"title":..,"head":"pr/126","base":"master"}   -> 201, user.login = davidxia
PATCH /api/v1/repos/spike-org/mirror-test {"allow_manual_merge":true,...}                              -> 200
POST /api/v1/repos/spike-org/mirror-test/pulls/<i>/merge (Sudo: davidxia) {"Do":"manually-merged","MergeCommitID":"<sha>"}  -> 200
```

## 1. Does the PR files endpoint work on a manually-merged PR?

**Yes, if the PR is opened while the base branch is still at `merge_commit_sha^1`. Naively it fails for some merge styles.** The endpoint is `GET /repos/{o}/{r}/pulls/{n}/files?page=&limit=` (`dagster/app/gitea.py`, `get_pull_request_files`).

Naive flow (push master at the tip, then open and manually merge):

```
PR #140 (squash)   GET /pulls/2/files?page=1&limit=50 -> HTTP 200, 18 files [README.md changed +2/-0, ...]   OK
PR #109 (squash)   GET /pulls/3/files                 -> HTTP 200, 2 files [__tests__/setup-pip.sh, requirements.txt]   OK
PR #126 (merge)    GET /pulls/1/files                 -> HTTP 200, []      (pull: changed_files 0, merge_base == head sha b98f5d9f)   EMPTY
PR #97  (ff)       GET /pulls/4/files                 -> HTTP 200, []      (changed_files 0)   EMPTY
```

Cause: the diff is merge_base(head, base)..head. When the PR head is already reachable from the base (merge commit, fast-forward), the merge base is the head and the diff is empty. Squash and rebase heads are not reachable, so they work as they are.

Fix, tested (`spike/04_rewind.sh <n>`): for each PR, force-push Gitea's base branch to `merge_commit_sha^1`, open the PR, fast-forward the base to `merge_commit_sha`, mark `manually-merged`, and later fast-forward to the tip:

```
PR #126 (merge)  master -> 02fbd091^1; POST /pulls (Sudo davidxia) -> 201, changed_files 1
                 GET /pulls/6/files   -> 200, 1 file [mkdocs_monorepo_plugin/merger.py changed]
                 master -> 02fbd091; POST /pulls/6/merge {"Do":"manually-merged","MergeCommitID":"02fbd091..."} -> 200
                 pull: merged true, changed_files 1, additions 1, deletions 1, merge_base b1965a21 (the real fork point)
                 GET /pulls/6/files   -> 200, 1 file    (after merge)
                 master -> tip f62ae22e; GET /pulls/6/files -> 200, 1 file   (stable once master moves on)
PR #97  (ff)     same flow: files while open 2, after merge 2, after master at tip 2 [README.md, setup.py]
```

The merge base is stored on the pull request at merge time and does not change when the base branch later moves. The sensors' list call also works on these: `GET /pulls?state=closed&limit=..` returns `number, merged_at, merge_commit_sha, user.login, base.ref` (`base.ref` is filtered client-side by the sensor).

## 2. Does manually-merged work for squash and rebase merges (merge commit not a descendant of the PR head)?

**Yes.** #140 and #109 (squash, head not an ancestor) were marked merged at their GitHub `merge_commit_sha`; #97 (merge commit == head) too:

```
POST /pulls/2/merge {"Do":"manually-merged","MergeCommitID":"c85e91f3518a4a1594e8eb496e0b67f4358f024b"}  -> 200
GET  /pulls/2 -> merged true, state closed, merge_commit_sha c85e91f3518a4a1594e8eb496e0b67f4358f024b
```

Two preconditions found:
- `{"message":"merge strategy is not allowed or is invalid [repo_id: 1, strategy: manually-merged]"}` (HTTP 400) until the repository has `allow_manual_merge: true` (set by `PATCH /repos/{o}/{r}`).
- `{"message":"commit not found in base branch"}` (HTTP 400) if `MergeCommitID` is not yet in the Gitea base branch (seen when master had been rewound). The commit must already be on the pushed base when you mark it merged.

A true rebase merge with rewritten commits was not found upstream; it has the same shape as squash (head not an ancestor), so it is expected to behave the same.

## 3. Is `merged_at` GitHub's time or the sync time? Can it be set?

**Sync time. It cannot be set through the API.**

```
GitHub PR #126:  merged_at 2025-01-30T19:03:52Z
Gitea  PR #1:    merged_at 2026-10-16T04:52:32Z   (the moment of the /merge call), created_at 2026-10-16T04:52:26Z
```

The swagger definitions in this Gitea version: `MergePullRequestOption` = `delete_branch_after_merge, do, force_merge, head_commit_id, merge_commit_id, merge_message_field, merge_title_field, merge_when_checks_succeed`; `CreatePullRequestOption` has no timestamps either. Extra `merged_at`/`created_at` fields I sent in the create and merge bodies were silently ignored (PR #5/#6: `created_at` 2026-10-16T04:53:xx, not 2020-01-01). Consequence: the sensor's `merged_after` cursor works on sync time, which is monotonic and fine, but the upstream merge time must be carried in the webhook event and the service's own table (`merged_at` in the ADR event is the GitHub time, not Gitea's). Only Gitea's migration importer or direct DB edits can preserve original times; neither fits the sync loop.

## 4. Normal repository vs pull mirror

**Recommend a normal repository (as ADR 0020 says).**

Pull mirror (`POST /repos/migrate {"service":"git","mirror":true,...}`, no token):

```
repo: mirror true, has_pull_requests false
git ls-remote: 78 refs/pull/N/*, 1 refs/heads/master, 1 refs/heads/agentbellnorm-patch-2, 1 refs/tags/0.4.3
POST /repos/spike-org/pullmirror/pulls (Sudo davidxia) -> 404 {"message":"not found"}
```

- A pull mirror cannot hold pull requests at all (the PR API is 404, `has_pull_requests` false), so it cannot satisfy the sensors.
- It also imports GitHub's `refs/pull/*`, whose numbers are GitHub's. In the normal repository Gitea writes its own `refs/pull/<gitea_index>/head` for every PR it creates. Evidence of the clash: in `mirror-test`, `refs/pull/1/head` = b98f5d9f (the head of GitHub #126); in the pull mirror, `refs/pull/1/head` = 1db4278f (GitHub PR #1). Same ref name, different meaning.
- A normal repository rejects direct pushes into the namespace, so GitHub's PR heads must be pushed as `pr/<n>` branches:
  `git push <gitea> refs/pull/140/head:refs/pull/140/head` -> `remote: error: hook declined to update refs/pull/140/head`, `! [remote rejected] ... (hook declined)`.

## Surprises (affect the sync engine, stage m5)

1. **Order of operations is required for merge-commit and fast-forward PRs.** Pushing the full base branch first yields empty `/files` for them (item 1). The sync must replay each PR in `merged_at` order: set base to `merge_commit_sha^1` (force push), open the PR, fast-forward base to `merge_commit_sha`, `manually-merged`, then continue. This needs force-push on the Gitea base branch (no branch protection on it), a per-mirror lock, and `merge_commit_sha^1` may not be the previous PR's merge (parallel PRs), so a force push (not just fast-forward) is expected. Alternative to test later: open the PR against a throwaway `base/<n>` branch at `merge_commit_sha^1`; not tested, and `base.ref` would then not equal the base branch the sensors filter on.
2. **Gitea PR index is not the GitHub number.** Indexes are assigned 1, 2, 3 in creation order (GitHub #126 became Gitea #1, #140 became #2). The node reads `/pulls/{index}/files`, so the webhook event must carry the Gitea PR number (and the GitHub number as an extra field). `mirrored_pull_requests` must store both.
3. **A second PR can be opened for a head that already has a merged PR** (#126 became Gitea #1, #5, #6). Idempotency must rely on `unique(mirror_id, number)` before creating, not on Gitea refusing duplicates. The spike's #1, #5 and #6 for the same head were my own retries.
4. **`manually-merged` is disabled by default per repository** and needs `allow_manual_merge: true`; the repo create call should set it.
5. **Shadow users must be collaborators with write on a private repository** to open PRs with `Sudo` (added with `PUT /collaborators/{user}`); the org-level approach (team membership) is the alternative. Users get `merged_by` set to the shadow user (the Sudo user).
6. `merged_at`, `created_at` are sync time and not settable (item 3).
7. The pull-mirror remote ref list holds `refs/pull/*/merge` entries too (78 refs for 66 PRs), irrelevant for a normal repository.
8. Gitea 28.1.0 is what the chart pins; it runs fine standalone with sqlite and `INSTALL_LOCK`. The admin token command needs `--scopes all` (or an explicit scope list).

## Verdict

**GO.** The files endpoint returns correct files on manually-merged PRs for merge-commit, squash and fast-forward PRs, provided the sync replays PRs in order with the base branch at `merge_commit_sha^1` when opening each (surprise 1). It returned empty (no failure) for merge-commit and fast-forward PRs under the naive flow, so m5 should be Opus-grade per the plan's "if the spike shows surprises" rule.
