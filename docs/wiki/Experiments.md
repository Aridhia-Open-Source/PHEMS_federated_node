# Experiments

An **experiment** is a real task image run against a real Postgres database with dummy data, on the development node. Its dataset's credentials go through nexus-api's secret, and its results are delivered to Gitea, so it exercises the whole path. This page is for people developing analytics images or the node itself. For a real node, see [Set up a project](./Set-Up-A-Project).

The experiments' databases are their own Helm release in the `experiments` namespace, apart from the FN chart. The node only sees the dataset that `fncli` registers, at `db-datasets.experiments.svc`. You need the development cluster running ([Run locally](./Run-Locally)).


## What is in an experiment

Everything an experiment needs lives in one folder, `experiments/<name>/`:

| File | What it is |
|---|---|
| `values.yaml` | The experiment's entry for the databases chart: it makes the database, the role and a generated password secret (`db-datasets-<name>`, with `username` and `password`) |
| `dataset.yaml` | A node file with only the dataset and its secret, read from the chart's secret. No project, no repositories |
| `seed.sh`, `seed/` | Prints the SQL that fills the database. Must be safe to rerun |
| `docker-bake.hcl`, `image/` | The task image's source and its build target, `<name>-fn` |
| `trigger.json` | The trigger file `run` sends: the image, and whatever else the task is asked for (CPU and memory limits, say) |
| `project.env` | Settings of `run` only: `RUN_TIMEOUT` |

The project and its repositories stay in node files under `bootstrap/examples/` (`globals-<name>.yaml` and `projects/<name>.yaml`), which assign the dataset by name.

`demo` is the smallest experiment: a database `demo-db` with a role `demo_user`, a tiny `cdm.person` table and an empty `results` schema, and a task image `demo-fn` that writes mock results. It has no project of its own: the demo node files hold the repositories and the project.


## Run an experiment

```sh
fncli experiment deploy                    # install the databases release (safe to rerun)
fncli experiment build NAME            # build and push the task image
fncli experiment seed NAME             # load the dummy data
fncli experiment setup NAME            # check the names, register the dataset, then the repositories and project
fncli experiment run NAME              # trigger a pull request, follow the task to the results pull request
```

They are safe to rerun after a failure. `setup`, `run`, `teardown` and `down` talk to the node, so they need your context file ([Using fncli](./Using-fncli#the-context-file)). If `fncli experiment` says "No such command", reinstall fncli from this checkout.

`setup` first checks that `dataset.yaml` names what the chart makes: its dataset is `dbs.<name>.name` of `values.yaml`, and its secret reads the Kubernetes secret `dbs.<name>.secret.name` in `experiments`. A name that does not match fails here, before the node gets a dataset it cannot use. Then it applies `dataset.yaml`, and the experiment's globals and project files if it has them.

`run` takes its pull request's project and repositories from the project file and the node, and the task's image from `trigger.json`. It adds `DEV_ENV` from your shell (JSON) to the task's `env`, which is how a quick run is asked for (`DEV_ENV='{"SOME_FLAG": "1"}' fncli experiment run NAME`). `FULL=1` leaves it out.

To run just the image, against the database and with no node:

```sh
fncli experiment run NAME --local
```

It needs `fncli` directly, because `make` would take the `--` option for itself. The results land under `experiments/results/NAME/`.


## Add an experiment

1. Put the image's source in `experiments/sources/NAME` (or in `experiments/NAME/image/`). The image reads the task contract ([Analytics container development](./Analytics-Container-Development)): `CONNECTION_STRING`, `CDM_SCHEMA`, `WRITE_SCHEMA`, and it writes to `ARTIFACT_PATH`.
2. Copy an existing experiment folder to `NAME`, and change the names and the seed: `values.yaml` (`dbs.NAME`), `dataset.yaml` (the dataset and secret must match it), `trigger.json` (the image), `project.env`, and copies of the globals and project node files for the repositories and the project.
3. Run `fncli experiment deploy`. It upgrades the release with the new database, so it works on a running cluster. Then `build`, `seed`, `setup` and `run`.

A dataset name is unique across the node, so two experiments cannot share one. A node file whose project names a dataset that is not on the node is blocked, so `setup` the experiment before applying its project.


## Building images

Images are built with `docker buildx bake`. The repo's root `docker-bake.hcl` holds the node's own images, and each experiment brings its own `docker-bake.hcl` with one target, `<name>-fn`, found automatically. An experiment whose source is not there (cloned separately) is skipped.

| Command | What it does |
|---|---|
| `make images` | Build and push the node's images and every experiment's target to the local registry |
| `make image NAME=<target>` | One target |
| `make image-reload NAME=<target>` | Push one target, then roll the deployments |
| `make images-release TAG=<tag>` | The release group, loaded into your local Docker, not pushed |
| `fncli experiment build NAME` | Build and push just one experiment's image |

Dev images are tagged `latest`. `make deploy` builds the default group for you.


## Check task isolation

`attacker` is a hostile task image, not an experiment. It tries to read other runs' folders, plant symbolic links and `../` paths in its output, reach nexus-api, Gitea and the Kubernetes API, read a service account token or another task's secret, and keep privileges. Each attempt prints `BLOCKED` or `LEAKED`, and the `PLANTED` lines are judged by what delivery does with them.

Run it like any experiment (`up`, `build attacker`, `seed attacker`, `setup attacker`, `run attacker`), then read `attack-report.txt` in the delivered `results.zip`, and check the zip holds no symbolic link or file from outside the run's folder. See [Architecture](./Architecture#task-isolation) for what is being tested.


## Clean up

- `fncli experiment teardown NAME` removes what `setup` registered in the node for NAME: its project and repositories (if it has node files), then its dataset and secret. The release and its database stay. The backend refuses to delete a dataset that another project still uses.
- `fncli experiment down` does that for every experiment, then uninstalls the release. The secrets and database files stay, so a later `setup` gets the same data back. If a demo project still uses `demo-db`, it stops: delete the demo project first.
- To start from empty: `kubectl delete ns experiments`, then delete `~/.fn/data/experiments`. Postgres owns it, so that needs root or the kind node.

The repo's [experiments/README.md](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/experiments/README.md) is the source for this page.
