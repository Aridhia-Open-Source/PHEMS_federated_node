# Session handover, 2026-10-17 (cloud session): gitea-mirror

Pointer note. The full state is in `project/handover/gitea-mirror-plan.md` ("Review 2026-10-17") and ADR 0020.

- **Parked for the beta.** The node uses GitHub directly. After the beta the mirror becomes a stateless service, in its own network zone,
  that replays PRs in number order so the Gitea numbers match GitHub's. The node sees it as a `gitea` `GitProvider`. Webhooks were dropped
  from the plan.
- **Done on this branch:** the review fixes were tested against a real Gitea and merged here (head `3b551cb7`): duplicate-PR lookup by head
  `pr/<n>`, base-branch restore, quarantine of poison PRs, `gh-` shadow users, GitHub token scoped to github.com, cursor ties, outbox
  leasing, a real Gitea admin token from the init job, unique RBAC names, and the fncli `mirror` commands.
- **Not done:** no e2e QA plan for this branch (chart deploy with the token job and no `helm install --wait`, a real mirror against a real
  GitHub repo, webhook delivery); not rebased onto the latest `moonshot/shared-resources`. `scripts/fncli/cli.py` will conflict trivially
  with the fncli move into `dagster/fncli` and its own `mirror` import.
- **Where the rest of the work is:** `moonshot/shared-resources` (the backend) and `moonshot/e2e-failure-suite` (the e2e failure suite and
  the `REVOKED` result step). See `project/handover/session-handover-2026-10-17.md` on the former.
