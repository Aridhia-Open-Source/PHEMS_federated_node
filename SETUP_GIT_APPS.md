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
4. Store the credentials in a Kubernetes Secret and register the repositories as node resources
   (`config/github/demo-github.yaml` is the pattern, ADR 0032). Put the two ids in `.dev.env`
   as `GH_APP_ID` and `GH_INSTALLATION_ID`, and keep the key at `~/.config/phems/phems-sandbox.private-key.pem`:

```bash
kubectl create secret generic phems-sandbox-github-app -n fn-operator \
  --from-literal=APP_ID="$GH_APP_ID" --from-literal=INSTALLATION_ID="$GH_INSTALLATION_ID" \
  --from-file=PRIVATE_KEY=$HOME/.config/phems/phems-sandbox.private-key.pem
kubectl apply -f config/github/demo-github.yaml     # provider, NodeSecret, repositories and the project
kubectl get fn -n fn-operator                                # each resource's Synced and Message
fncli verify-git-secret --entity trigger --project demo-github   # nexus-api mints a token, GitHub accepts it
fncli verify-git-secret --entity results --project demo-github
```

Tokens last an hour and are scoped to the one repository. There are no refresh tokens.
GitHub OAuth Apps (user tokens) are not supported.

## Gitea: an OAuth2 application

The default dev setup. `fncli gitea setup -f config/gitea.yaml -f config/demo.yaml` creates the Gitea repositories of the file's Repository
resources and, for each NodeSecret they name, an OAuth2 application of that name for the admin user. It writes
`CLIENT_ID`, `CLIENT_SECRET` and `REFRESH_TOKEN` into the Kubernetes Secret the NodeSecret's `fromSecret` names, and
keeps a Secret that exists unless you pass `--rotate NODESECRET`. Run it before `kubectl apply` of the same file;
nexus-api refreshes from the values.
The chart pins Gitea's `INVALIDATE_REFRESH_TOKENS=false`, which is what makes concurrent
refreshes safe (see the concurrent-refresh e2e test).

## Notes

- Rewriting a secret replaces all its values, so cached tokens from old credentials are dropped.
- A static token (`TOKEN`) still works for either provider, as a fallback.
