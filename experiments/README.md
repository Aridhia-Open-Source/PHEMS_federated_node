# Experiments

Run real experiment images against the dev node. Each one has a real Postgres database with
dummy data, a dataset whose credentials go through nexus-api's secret, and results
delivered to Gitea.

The databases are their own Helm release in the `experiments` namespace (`chart/`), apart
from the federated-node chart. The node only sees the dataset that fncli registers, at
`db-datasets.experiments.svc`.

## Layout

| Path | Committed | What |
|---|---|---|
| `chart/` | yes | the datasets Postgres, plus a database, role and generated password per project |
| `projects/NAME/values.yaml` | yes | the project's `dbs.NAME` entry for the chart: it makes the database, the role and the `db-datasets-NAME` secret (`username` and `password`) |
| `projects/NAME/bootstrap.yaml` | yes | a node file with only the dataset and its secret, read from the chart's secret: no project, no repos |
| `projects/NAME/seed.sh`, `seed/` | yes | prints the SQL that seeds the database (or what it needs); must be safe to rerun |
| `projects/NAME/docker-bake.hcl` | yes | the `NAME-fn` bake target: builds the task image from `image/` (demo, attacker) or the cloned source (uc1), tagged `localhost:5001/NAME-fn`. `make deploy` and `make images` build it (uc1 only when its source is there); `fncli experiment build NAME` builds just this one and pushes it |
| `projects/NAME/image/` | no | the task image's source, when it lives here (demo, attacker) |
| `projects/NAME/project.env` | yes | the settings of `run` only: `IMAGE` (what the bake file builds), `RUN_TIMEOUT`; wins over `.dev.env` and the shell |
| `bootstrap/examples/experiments/NAME.yaml` | yes | the node file with the experiment's project, global repositories and Gitea repos, and the dataset by name (uc1, attacker) |
| `sources/NAME/` | no | the image's build context (often its own git repo) |
| `results/NAME/` | no | output of `run --local` |

## Run an experiment

Needs the dev cluster up with Tilt (port-forwards for nexus-api 5000, Gitea 4000 and Dagster
3000), `fncli` on PATH, and `.dev.env` at the repo root. An experiment's source may live in
its own repo, so it is not always in this one: clone it into `sources/<name>`. Notes for a
specific experiment are in `projects/<name>/README.md`.

```bash
fncli experiment up                    # the release: Postgres with every project's database
fncli experiment build <name>          # the project's image, pushed to the kind registry
fncli experiment seed <name>           # dummy data into the project's database
fncli experiment setup <name>          # name check, then the dataset, then the project with its repos
fncli experiment run <name> --local    # optional: image straight against the DB, no node
fncli experiment run <name>            # trigger PR -> task -> results PR in the project's results repo
```

See Clean up for `fncli experiment teardown NAME` and `down`. `seed` and `setup`
fail and tell you to run `up` if the release isn't installed. `up`, `seed`, `setup`, `run` and
`teardown` can be rerun after a failure. If `fncli experiment`
says "No such command", reinstall fncli from this checkout:
`pipx install --force --editable './dagster[cli]'`.

`setup` first checks that `bootstrap.yaml` names what the chart makes: its dataset is `dbs.NAME.name`
of `values.yaml`, and its secret reads the Kubernetes secret `dbs.NAME.secret.name` in `experiments`.
Then it applies `bootstrap.yaml` (`fncli apply -f`), and the project's node file if the experiment has
one. `run` takes its pull request's project and repositories from that node file, not from `.dev.env`.

`run` and `run --local` pass `DEV_ENV` from your shell (JSON) to the task. A project can use it for a
quick dev run (see its README), e.g. `DEV_ENV='{"EXAMPLE_FLAG": "1"}' fncli experiment run <name>`; with
no `DEV_ENV`, or with `FULL=1`, `run` is the whole thing.

## Add an experiment

1. Put the source in `sources/NAME`. Its image reads the task contract: `CONNECTION_STRING`
   (a full ODBC string, e.g. `driver={PostgreSQL ANSI};Uid=;Pwd=;Server=host,port;Database=;`), `CDM_SCHEMA`, `WRITE_SCHEMA`, and writes results
   to `ARTIFACT_PATH`.
2. Copy an existing project in `projects/` to `projects/NAME`, then change the names and the seed:
   `values.yaml` (`dbs.NAME`), `bootstrap.yaml` (the dataset and secret must match it), `project.env`,
   and a copy of one of `bootstrap/examples/experiments/*.yaml` for the project and its repos.
3. Run `fncli experiment up` (it upgrades the release with the new database, so this works
   on a running cluster), then `build NAME`, `seed NAME`, `setup NAME` and `run NAME`.

`projects/demo` is a no-op demo database (`demo-db`, user `demo_user`, a tiny `cdm.person` table and an empty `results` schema). It has no node project of its own, and no `project.env`: the demo node files (`bootstrap/examples/demo-gitea.yaml`, `demo-github.yaml`) hold the project and repos and assign the dataset by name (`datasets: [demo-db]`). Its task image is at `experiments/projects/demo/image`, built by its `docker-bake.hcl` as `demo-fn`.

```bash
fncli experiment up                          # the release: databases, roles, secrets
fncli experiment seed demo                   # the schemas and rows
fncli experiment setup demo                  # name check, then the dataset demo-db with its secret
fncli apply -f examples/demo-github.yaml     # project, repos, assigns demo-db (or demo-gitea.yaml)
fncli demo -f examples/demo-github.yaml      # the guided walk, with the dataset healthcheck
```

A node file whose project names a dataset that is not on the node is blocked (the plan says "not in the
file or on the node"), so apply the dataset first.

## Check task isolation

`projects/attacker` is a hostile task image, not an experiment. It tries to read other runs'
folders, plant symlinks and `../` paths in its output, reach nexus-api, Gitea and the
Kubernetes API, read a service account token or another task's Secret, and keep privileges. Each
attempt prints `BLOCKED` or `LEAKED`; `PLANTED` lines are judged by what delivery does with them.
Run it like any experiment (`up`, `build attacker`, `seed attacker`, `setup attacker`, `run attacker`), then
read `attack-report.txt` in the delivered `results.zip` in `attacker-results-repo`, and check the zip
holds no symlink or file from outside the run's folder. To plant a Secret to try for, create one
named `task-decoy` in the tasks namespace. `DEV_ENV` can set `OTHER_RUN_ID` (a run's folder
name to try to read) and `SLEEP_SECONDS` (to hang the task and see the pod's deadline end it).

## Clean up

- `fncli experiment teardown NAME` removes what `setup` registered in the node for NAME: its
  project and repositories (if it has a node file), then its dataset and secret. The release and
  its database stay. The backend refuses to delete a dataset that another project still uses.
- `fncli experiment down` does that for every experiment (every folder with a `bootstrap.yaml`),
  then uninstalls the release. The secrets and database files stay, so a later `setup` gets the
  same data back. If a demo project still uses `demo-db`, `down` stops with the backend's refusal
  and leaves the release: delete the demo project first, `fncli delete -f examples/demo-github.yaml --all -y`
  (or `demo-gitea.yaml`).
- Start from empty: `kubectl delete ns experiments`, then delete
  `~/.fn/data/experiments` (Postgres owns it, so you need root or the kind node).
