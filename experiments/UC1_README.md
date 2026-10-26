# UC1 on the dev node: from git clone to a results PR

UC1 is the cardiac benchmarking study (R, OMOP CDM 5.4). Its source is the private
`PHDS-centralized-services/MVP-Code` repo, so it is not in this one. Everything else is here:
`projects/uc1/` holds the database, the seed and the node project it runs as. The general
mechanics are in [README.md](README.md).

## Today: by hand

Needs the dev cluster up with Tilt (or the port-forwards for backend 5000, Gitea 4000 and
Dagster 3000), `fncli` on PATH, and `.dev.env` at the repo root. Run everything from the repo
root. If `make experiments` says "No such command", reinstall fncli from this checkout:
`pipx install --force --editable './dagster[cli]'`.

```bash
git clone https://github.com/PHDS-centralized-services/MVP-Code experiments/sources/uc1
make experiments up          # the experiments release, with the uc1-omop database
make experiments seed uc1    # dummy OMOP data into uc1-omop
make experiments setup uc1   # project "uc1" in the node
make experiments build uc1   # localhost:5001/uc1-fn:latest (slow: R package restore)
make experiments run uc1     # trigger PR -> task -> results PR in Gitea uc1-results-repo
```

`up`, `seed`, `setup` and `run` can be rerun after a failure. `fncli experiment run uc1 --local` runs the
image in docker straight against the database, with no node involved, to tell an analysis
failure from a node one.

| Step | What it does | Where |
|---|---|---|
| `up` | helm upgrade of the `experiments` release: Postgres, database `uc1-omop`, role `uc1_omop_user`, generated password | namespace `experiments` |
| `seed` | checks the release is up, loads the synthetic OMOP data over `kubectl exec` (recreating its schemas) | namespace `experiments` |
| `setup` | checks the release is up, then `fncli setup-project`: project `uc1`, Gitea repos `uc1-trigger-repo` and `uc1-results-repo`, their tokens, and the dataset at `db-datasets.experiments.svc` | backend + Gitea |
| `build` | `docker build experiments/sources/uc1`, push to the kind registry | host Docker |
| `run` | starts the sensors, opens and merges a spec PR, watches the task and the results PR | Gitea + Dagster |

A full run takes about 8 minutes, nearly all of it in the R cohort building. The data is
small (832 patients); the time goes on the many small queries the R packages run.

### Tear down and redeploy

```bash
make experiments teardown uc1   # remove project "uc1", its global resources and Gitea repos
make experiments down           # or: teardown every experiment, then uninstall the release
make experiments up             # back again (the database files survive `down`)
make experiments setup uc1      # `seed uc1` too if you wiped the data
make experiments run uc1        # `build uc1` first only if the source changed
```

To start from empty data, after `down`: `kubectl delete ns experiments` and
`sudo rm -rf ~/.fn/data/experiments`.

### Dev mode

`run` and `run --local` pass `DEV_ENV` from `projects/uc1/project.env` (`UC1_DEV=1`) to the
task: fewer cohorts, for proving the pipeline. `FULL=1 make experiments run uc1` runs the
whole study. `UC1_DEV` needs R changes that are not on MVP-Code's main yet. Without them
the variable is ignored and the full study runs, which still works, only slower.

## Planned: one command

```bash
make experiments all uc1
```

Not built yet. It would run, in order:

1. **Clone** when `sources/uc1` is missing: `SOURCE_REPO` and `SOURCE_REF` from
   `project.env`, authenticated with `GH_TOKEN` from `.dev.env` (it needs read access to
   MVP-Code), so nobody has to log in. An existing `sources/uc1` is left as it is.
2. **`setup`**, **`build`**, **`run`** as above.

Each step is idempotent, so a failed `all` is fixed and run again.

Also planned: `run --local` waits for its port-forward with a socket connect instead of
`pg_isready`, so the host needs no Postgres client.

Open:

- `SOURCE_REF`: MVP-Code's `main`, or a branch carrying the dev-mode R changes (needs the
  MVP-Code owners' agreement).
