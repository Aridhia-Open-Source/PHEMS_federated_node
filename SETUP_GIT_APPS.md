# Setting up git apps

The node never stores a long-lived git token. Each repository's secret holds app credentials, and
nexus-api mints a short-lived token from them when Dagster asks
(`POST /global/repositories/{triggers,results}/{id}/token`, ADR 0024). Gitea and GitHub repositories
can be used side by side: the secret's keys pick the token type, and the repository's provider picks
the API client.

## GitHub: a GitHub App

1. Create the App (org settings → Developer settings → GitHub Apps → New):
   - untick Webhook "Active";
   - Repository permissions: **Contents** and **Pull requests**, read and write;
   - "Only on this account"; leave the user-authorisation options off.
2. Note the **App ID**, then **Generate a private key** (a `.pem`; keep it out of git).
3. **Install App** on only the repositories the node uses. The number at the end of the
   installation URL is the **installation ID**.
4. Store the credentials and register the repositories from a node file
   (`bootstrap/examples/globals-github.yaml` is the pattern). Put the two ids in `.dev.env` (the `node.env_file` of
   your `bootstrap/context.yaml`, `cp bootstrap/examples/context.yaml bootstrap/context.yaml`)
   as `GH_APP_ID` and `GH_INSTALLATION_ID`, and the key at the path the file names (`~/.config/phems/phems-sandbox.private-key.pem`):

```bash
fncli diff  -f examples/globals-github.yaml     # what it would create; shows each value's source, never the value
fncli apply -f examples/globals-github.yaml
fncli apply -f examples/projects/demo-github.yaml   # the project the checks below work on: its repos are read from the node
fncli verify-git-secret --entity trigger --project demo-github   # nexus-api mints a token, GitHub accepts it
fncli verify-git-secret --entity results --project demo-github
```

Tokens last an hour and are scoped to the one repository. There are no refresh tokens.
GitHub OAuth Apps (user tokens) are not supported.

## Gitea: an OAuth2 application

The default dev setup. `fncli apply` of a node file with a `gitea_oauth` secret creates an OAuth2 application for the admin user
and stores `CLIENT_ID`, `CLIENT_SECRET` and `REFRESH_TOKEN`; nexus-api refreshes from them.
The chart pins Gitea's `INVALIDATE_REFRESH_TOKENS=false`, which is what makes concurrent
refreshes safe (see the concurrent-refresh e2e test).

## Notes

- Rewriting a secret replaces all its values, so cached tokens from old credentials are dropped.
- A static token (`TOKEN`) still works for either provider, as a fallback.
