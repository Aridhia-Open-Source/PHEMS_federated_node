# 0023. Short-lived git tokens, minted by the backend (GitHub App and Gitea OAuth2)

Status: proposed, not built.

## Context

The node must authenticate to GitHub as a GitHub App, not with personal access tokens. An App installation token lives for one hour and cannot be extended. Today every repository's secret holds a long-lived `TOKEN` ([0007](0007-secrets-and-secret-providers.md)), and Dagster reads it directly in two places: `GitAPIFactory.for_repository` ([0010](0010-git-api-protocol-and-factory.md)) and the results delivery push (`git_push.auth_env`). The previous node refreshed a shared token with a bash script in the federated-node-controller repo, which nothing else could reuse.

Gitea has no App installation tokens, but it is an OAuth2 provider: an access token lives for one hour (`ACCESS_TOKEN_EXPIRATION_TIME = 3600`) and a refresh token for 730 hours (`REFRESH_TOKEN_EXPIRATION_TIME`); a used refresh token stays valid unless `INVALIDATE_REFRESH_TOKENS` is set (default `false`), per Gitea's `custom/conf/app.example.ini`. Using the same shape for both lets the Gitea dev cluster test short-lived auth end to end.

Pull requests belong to the global trigger repository, and every project assigned to it uses that repository's credential ([0011](0011-pull-requests-stored-once-fan-out-and-cursors.md)). `ProjectTriggerRepository` has no secret of its own. No open-source broker was found that covers both GitHub and Gitea.

## Decision

- **Credentials stay on the global repository.** The secret of each global trigger repository and results repository ([0006](0006-global-resources-and-project-resources.md)) holds a long-lived credential that the backend exchanges for a one-hour access token. Every project assigned to the repository uses it, as today. The secret holds one of:
  - GitHub App: `APP_ID`, `INSTALLATION_ID`, `PRIVATE_KEY`.
  - Gitea OAuth2: `CLIENT_ID`, `CLIENT_SECRET`, `REFRESH_TOKEN`.
  - Static: `TOKEN` (returned as is; kept for setups not yet moved over).
- **The backend is the only reader of git secrets.** Dagster no longer reads them.
- **The backend mints on request.** `POST /global/repositories/triggers/{id}/token` and `POST /global/repositories/results/{id}/token` return `{token, expires_at}`. An optional `project_id` names the project the token is for.
  - GitHub: sign a JWT with `PRIVATE_KEY`, exchange it for an installation token restricted to that one repository and its permission (read for a trigger repository, write for a results repository).
  - Gitea: exchange `REFRESH_TOKEN` (with `CLIENT_ID` and `CLIENT_SECRET`) at `/login/oauth/access_token`, and write the returned refresh token back to the secret.
- **The backend caches the access token in the repository's secret**, keyed by repository and permission, with its expiry. A token with more than five minutes left is returned without minting. Every backend worker shares the cache.
- **No lock.** Two requests that both find no valid cache both mint. For GitHub, many installation tokens are valid at once. For Gitea, both refreshes succeed because a used refresh token stays valid; the last refresh token written wins and the others are held nowhere. The Helm values pin `INVALIDATE_REFRESH_TOKENS = false` for the in-cluster Gitea, since turning it on would make the second refresh fail.
- **The backend refuses** (cached or not) with 403 for a repository, its provider or its secret that is disabled or revoked, and, when `project_id` is given, for a project or assignment that is revoked (a deleted one counts as revoked) or that the project does not have. A disabled project or assignment still gets a token, because its finished results are delivered while it is off ([0008](0008-enabled-revoked-and-soft-delete.md)). A token already handed out stays valid for at most an hour.
- **Dagster asks at the moment of use.** `GitAPIFactory.for_repository` and the delivery push call the endpoint instead of `read_secret_value(..., "TOKEN")`, just before the API calls or git command that need the token, never at the start of a run, so a run longer than an hour still pushes its results.
- **The token is never stored outside the cache.** It travels in the HTTP response and reaches git through its environment (`git_push.auth_env`). There is no Kubernetes secret per task.

## Consequences

- One path for GitHub and Gitea; the Gitea dev cluster exercises minting, caching and expiry end to end. A new provider is a token source next to its client ([0010](0010-git-api-protocol-and-factory.md)).
- Dagster pods no longer read git secrets, which narrows their secret access ([0022](0022-task-isolation.md)).
- Every token issued can be recorded: which repository, which permission, for which project.
- Per-project revocation is done on the node (the backend stops handing out tokens). On GitHub a data controller revokes per repository, by removing it from the App installation or uninstalling the App; GitHub has no finer switch.
- A Gitea OAuth2 token acts as the user who authorised it, not as one repository, so that service user should only have access to the repositories it needs.
- A Gitea repository unused for 30 days loses its refresh token and needs authorising again.
- Git calls now depend on the backend being up, as the rest of the pipeline already does ([0021](0021-webserver-owns-the-record-and-the-rules.md)).
- The minting code is a module inside the backend behind a small interface; it can move to its own service later without changing callers.

## Alternatives considered

- **Dagster mints the token itself** (for example with PyGithub's `Auth.AppInstallationAuth`): every code server and run pod would need the private key, and node-side revocation would have to be checked in Dagster.
- **A refresh job writing the current token into a shared secret** (the previous node's script): readers can hold a stale token, and a single shared token cannot be limited per repository.
- **A temporary Kubernetes secret per task:** it still expires after an hour, so a long task cannot push with it, and each secret needs cleanup.
- **Per-project credentials:** GitHub cannot revoke per project, so this adds secrets without giving data controllers a finer control.
- **Static tokens for Gitea:** simpler, but GitHub's path could not be tested locally.
- **An existing broker** (Octo STS, the Vault GitHub secrets plugin, External Secrets' GitHub generator): GitHub-only, and none checks the node's revoked and enabled flags.
- **A separate token service now:** smaller blast radius for the keys, but another deployment and service-to-service auth; deferred.
