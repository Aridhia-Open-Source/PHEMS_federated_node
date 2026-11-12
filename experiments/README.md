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
| `projects/NAME/project.env` | yes | image, database, and the node project and Gitea repos fncli sets up; wins over `.dev.env` and the shell |
| `projects/NAME/values.yaml` | yes | the project's `dbs.NAME` entry for the chart |
| `projects/NAME/seed.sh` | yes | prints the SQL that seeds the database; must be safe to rerun |
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
fncli experiment setup <name>          # the project in the node, with its global resources
fncli experiment run <name> --local    # optional: image straight against the DB, no node
fncli experiment run <name>            # trigger PR -> task -> results PR in the project's results repo
```

See Clean up for `fncli experiment teardown NAME` and `down`. `seed` and `setup`
fail and tell you to run `up` if the release isn't installed. `up`, `seed`, `setup`, `run` and
`teardown` can be rerun after a failure. If `fncli experiment`
says "No such command", reinstall fncli from this checkout:
`pipx install --force --editable './dagster[cli]'`.

`run` and `run --local` pass the project's `DEV_ENV` (JSON, from `project.env`) to the task.
A project can use it for a quick dev run (see its README). `FULL=1 fncli experiment run
<name>` skips it and runs the whole thing.

## Add an experiment

1. Put the source in `sources/NAME`. Its image reads the task contract: `CONNECTION_STRING`
   (a full ODBC string, e.g. `driver={PostgreSQL ANSI};Uid=;Pwd=;Server=host,port;Database=;`), `CDM_SCHEMA`, `WRITE_SCHEMA`, and writes results
   to `ARTIFACT_PATH`.
2. Copy an existing project in `projects/` to `projects/NAME`, then change the names and the seed.
3. Run `fncli experiment up` (it upgrades the release with the new database, so this works
   on a running cluster), then `build NAME`, `seed NAME`, `setup NAME` and `run NAME`.

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

- `fncli experiment teardown NAME` removes what `setup` registered in the node for NAME. The
  release and its database stay.
- `fncli experiment down` tears down every experiment's node project, then uninstalls the
  release. The secrets and database files stay, so a later `setup` gets the same data back.
- Start from empty: `kubectl delete ns experiments`, then delete
  `~/.fn/data/experiments` (Postgres owns it, so you need root or the kind node).
