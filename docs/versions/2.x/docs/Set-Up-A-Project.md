# Set Up a Project

This is the admin's guide to what a node needs before it can run anything: the global resources (secrets, a git provider, repositories, a dataset) and a **project** that uses them. Install the node first ([Deploy: Core](./Deploy-Core)).

On a real node, set these up with the API, as this page shows. [Using fncli](./Using-fncli) does the same from files on a development cluster, and both create the same records.

The commands are written from the API's request models. They are a guide: the API's own reference is at `/docs` on your node.


## How it fits together

Secrets, datasets, git providers, and trigger and results repositories are **global**: they belong to no project and are created once, by an admin. A project is then assigned the ones it uses. Each assignment holds what is per project: which directory to watch, where results go, and the enabled and revoked flags. See [Architecture](./Architecture#global-resources-and-projects).

Create them in this order, because each one refers to the one before:

| # | What | Needs | Holds |
|---|---|---|---|
| 1 | Secret | nothing | A git App's credentials for each repository, and the dataset's database login. Stored in Kubernetes; the API never returns the values |
| 2 | Git provider | nothing | The git host: GitHub or Gitea, with its web and API addresses |
| 3 | Trigger repository | provider, secret | The repository whose merged pull requests become tasks |
| 4 | Results repository | provider, secret | The repository results are pushed to, as a branch and a pull request |
| 5 | Dataset | secret | A database the tasks read, and where they may write |
| 6 | Project | nothing | The unit of work. Created **disabled** |
| 7 | Assignments | project, and 3, 4, 5 | The trigger repository (`watch_dir`, `base_branch`), the results repository (`target_dir`), the dataset |
| 8 | Enable the project, start the sensors | 7 | Nothing runs before this |


## Before you start

You need the admin login (the first user from the install) and the node's address.

```sh
FN=https://fn.your-institution.example.com

TOKEN=$(curl -sS -X POST "$FN/login" \
  -F "username=admin@your-institution.example.com" \
  -F "password=<the first user's password>" | jq -r .token)

AUTH=(-H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json")
```

`/login` takes form fields, not JSON. The token lasts 8 hours, and `POST /refresh_token` renews it. Creating global resources and revoking things is **admin only**.


## Git hosts and credentials

The node never stores a long-lived git token. Each repository's secret holds app credentials, and nexus-api mints a short-lived token from them each time Dagster needs one. The keys in the secret say which kind it is:

| Git host | Secret keys | Token |
|---|---|---|
| GitHub (a GitHub App) | `APP_ID`, `INSTALLATION_ID`, `PRIVATE_KEY` | One hour, covering the one repository |
| Gitea (an OAuth2 application) | `CLIENT_ID`, `CLIENT_SECRET`, `REFRESH_TOKEN` | One hour, refreshed from the refresh token |
| Either, as a fallback | `TOKEN` | A static token, used as it is |

GitHub and Gitea repositories can be used side by side. The repository's provider picks the API client.

### GitHub

1. Create the App (your organisation's settings, Developer settings, GitHub Apps, New):
   - untick Webhook "Active";
   - Repository permissions: **Contents** and **Pull requests**, read and write;
   - "Only on this account", and leave the user-authorisation options off.
2. Note the **App ID**, then generate a **private key** (a `.pem` file). Keep it out of git.
3. **Install** the App on only the repositories the node uses. The number at the end of the installation URL is the **installation ID**.

GitHub OAuth Apps (user tokens) are not supported. To withdraw the node's access on GitHub, remove the repository from the App's installation, or uninstall the App: GitHub has no finer switch.

### Gitea

Gitea is the development host. The chart can run one for you (`gitea.enabled`), and `fncli apply` creates and authorises the OAuth2 application for you: see [Using fncli](./Using-fncli). The chart pins Gitea's `INVALIDATE_REFRESH_TOKENS=false`, which makes concurrent refreshes safe. A Gitea repository that goes unused for 30 days loses its refresh token and needs authorising again.


## 1. Secrets

Make one per credential. A **label** is the name you use for it in later calls. It also becomes part of a Kubernetes name, so use lowercase letters, digits, `-` and `.`.

```sh
# A GitHub App for a repository (here shared by the trigger and the results repository)
jq -n --rawfile key your-app.private-key.pem '{
  label: "demo-repo-creds", provider: "K8S",
  values: {APP_ID: "<app id>", INSTALLATION_ID: "<installation id>", PRIVATE_KEY: $key}
}' | curl -sS -X POST "$FN/global/secrets" "${AUTH[@]}" -d @- | jq

# The dataset: the database login. The keys are USERNAME and PASSWORD
curl -sS -X POST "$FN/global/secrets" "${AUTH[@]}" -d '{
  "label": "demo-dataset-creds", "provider": "K8S",
  "values": {"USERNAME": "<db user>", "PASSWORD": "<db password>"}
}' | jq
```

To rotate a value later: `PATCH $FN/global/secrets/<label>` with `{"values": {...}}`. Rewriting a secret replaces all its values, and cached tokens from the old credentials are dropped.


## 2. Git provider

One per git host. Repositories on the same host share it.

```sh
PROVIDER_ID=$(curl -sS -X POST "$FN/global/providers" "${AUTH[@]}" -d '{
  "name": "github", "type": "github",
  "uri": "https://github.com", "api_uri": "https://api.github.com"
}' | jq -r .id)
```

`type` is `github` or `gitea`. `uri` is the host's web address and `api_uri` its API base URL (for Gitea: `https://<host>/api/v1`).


## 3. Trigger and results repositories

`repo_path` is `owner/name`. `secret_label` is the secret from step 1. The repositories have to exist already.

```sh
TRIGGER_ID=$(curl -sS -X POST "$FN/global/repositories/triggers" "${AUTH[@]}" -d "{
  \"provider_id\": $PROVIDER_ID,
  \"repo_path\": \"your-org/fn-triggers\",
  \"secret_label\": \"demo-repo-creds\"
}" | jq -r .id)

RESULTS_ID=$(curl -sS -X POST "$FN/global/repositories/results" "${AUTH[@]}" -d "{
  \"provider_id\": $PROVIDER_ID,
  \"repo_path\": \"your-org/fn-results\",
  \"secret_label\": \"demo-repo-creds\"
}" | jq -r .id)
```

One repository can be both the trigger and the results repository. Then the project's `watch_dir` and `target_dir` must not overlap, so that the results pull requests are not mistaken for triggers.


## 4. Dataset

```sh
DATASET_ID=$(curl -sS -X POST "$FN/global/datasets" "${AUTH[@]}" -d '{
  "name": "uc1_omop",
  "host": "<dataset database host>",
  "port": 5432,
  "type": "postgres",
  "secret_label": "demo-dataset-creds",
  "read_schema": "cdm",
  "write_schema": "results"
}' | jq -r .id)
```

Fields, types and the checks that matter are on the [Datasets](./Datasets) page. Check the dataset is reachable now, instead of when the first task fails: `GET /global/datasets/$DATASET_ID/healthcheck`.

Tasks can only reach the database if its address is in the chart's `taskNetworkPolicy.datasetEgress` ([Deploy: Core](./Deploy-Core#let-tasks-reach-their-dataset)).


## 5. Project

A new project is **disabled**. That is deliberate: the results repository can only be assigned while the project is disabled.

```sh
PROJECT_ID=$(curl -sS -X POST "$FN/projects" "${AUTH[@]}" -d '{
  "name": "uc1-demo", "description": "First project", "enabled": false
}' | jq -r .id)
```


## 6. Assign the resources to the project

`PUT` assigns. The id in the URL is the **global resource's id**, not the assignment's. A repeat `PUT` replaces the project's settings for that resource.

```sh
# Dataset. The first dataset assigned becomes the project's default
curl -sS -X PUT "$FN/projects/$PROJECT_ID/datasets/$DATASET_ID" "${AUTH[@]}" -d '{}' | jq

# Trigger repository: the directory to watch, and the branch merges are tracked on
curl -sS -X PUT "$FN/projects/$PROJECT_ID/repositories/triggers/$TRIGGER_ID" "${AUTH[@]}" -d '{
  "watch_dir": "specs/", "base_branch": "main"
}' | jq

# Results repository: the directory results go under, and the branch results pull requests start from and go into
curl -sS -X PUT "$FN/projects/$PROJECT_ID/repositories/results/$RESULTS_ID" "${AUTH[@]}" -d '{
  "target_dir": "results/", "base_branch": "main"
}' | jq
```

- `base_branch` is required for both repositories. It is never guessed from the repository's default branch.
- `watch_dir` must not be empty. Only a pull request that adds a `.json` file under it becomes a task.
- A project has one results repository.
- The trigger assignment's starting point is set when you assign it. Pull requests merged before that are not run, unless you ask for a backfill when enabling the project.


## 7. Check, then enable

```sh
curl -sS "$FN/projects/$PROJECT_ID/healthcheck" "${AUTH[@]}" | jq      # can every resource be reached with its token?
curl -sS "$FN/global/healthcheck" "${AUTH[@]}" | jq                     # the whole node
```

A failing check (a wrong token, an unreachable database or git host) shows in the body, never as a 500, and never contains a secret value. Fix what it names, then:

```sh
curl -sS -X PATCH "$FN/projects/$PROJECT_ID" "${AUTH[@]}" -d '{"enabled": true}' | jq
```

Enabling skips pull requests that were stored while the project was off. To have them run, send `{"enabled": true, "backfill": true}` instead.

Finally, **start the sensors**. Nothing is polled until you do: see [Operations](./Operations#start-the-sensors). Then a researcher can ask for a task: [Researcher guide](./Researcher-Guide).


## Add another project

A second project reuses the global resources: create the project, then assign the same ids.

```sh
PROJECT2_ID=$(curl -sS -X POST "$FN/projects" "${AUTH[@]}" -d '{"name": "second-project"}' | jq -r .id)

curl -sS -X PUT "$FN/projects/$PROJECT2_ID/datasets/$DATASET_ID" "${AUTH[@]}" -d '{}'
curl -sS -X PUT "$FN/projects/$PROJECT2_ID/repositories/triggers/$TRIGGER_ID" "${AUTH[@]}" -d '{"watch_dir": "specs/", "base_branch": "main"}'
curl -sS -X PUT "$FN/projects/$PROJECT2_ID/repositories/results/$RESULTS_ID" "${AUTH[@]}" -d '{"target_dir": "results-two/", "base_branch": "main"}'
curl -sS -X PATCH "$FN/projects/$PROJECT2_ID" "${AUTH[@]}" -d '{"enabled": true}'
```

A merged pull request is stored once, whatever the number of projects watching the repository, and each project whose `watch_dir` and `base_branch` match gets its own task. The project's own dataset assignment decides which dataset its tasks use.


## More detail

The repo's [MANAGEMENT.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/MANAGEMENT.md) has the same walk with more notes, and [SETUP_GIT_APPS.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/SETUP_GIT_APPS.md) covers the git credentials.
