# Analytics Container Development

This guide covers everything you need to build a Docker container that runs as a task inside the Federated Node 2.x.

Your container receives database connection details, schema names, and any custom parameters as environment variables. It writes results to a folder it is given, and exits. That's the entire contract. This page is written from what the node does when it starts a task, so it also tells you what the container is *not* allowed to do.

How a researcher asks for your container to run is in the [Researcher guide](./Researcher-Guide).


## Quick start

The base images have the ODBC drivers pre-installed for the database engines the node supports:

| Image | Language |
|---|---|
| `ghcr.io/aridhia-open-source/python-base` | Python |
| `ghcr.io/aridhia-open-source/r-base` | R |

Source and current tags: [Federated-Node-Task-Base-Images](https://github.com/Aridhia-Open-Source/Federated-Node-Task-Base-Images)

Example `Dockerfile`:

```dockerfile
FROM ghcr.io/aridhia-open-source/python-base:<tag>

COPY requirements.txt /app/
RUN pip install -r /app/requirements.txt

COPY analysis.py /app/

CMD ["python", "/app/analysis.py"]
```

Install every dependency when you build the image. The running container has no internet access.


## What your container is given

| Variable | Set when | Description |
|---|---|---|
| `ARTIFACT_PATH` | always | The folder to write your results to. Exists and is writable. |
| `CONNECTION_STRING` | the task has a dataset | A complete ODBC connection string for the dataset's database. |
| `DB_USERNAME`, `DB_PASSWORD` | the task has a dataset | The database login. The connection string already contains them. |
| `CDM_SCHEMA` | the dataset has a read schema | The schema your queries should read from. |
| `WRITE_SCHEMA` | the dataset has a write schema | The schema to write results back to the database, if your analysis does. |
| `CONFIG_PATH` | the spec has a `config` | The path of a read-only JSON file holding the spec's `config`: `/etc/task/config.json`. |
| your own | the spec has an `env` | Each `spec.env` entry, with its name upper-cased. |

A task without a dataset gets none of the database variables. Names starting `DAGSTER_` are Dagster's own: ignore them.

**Your own variables arrive as text.** The node converts each `spec.env` value to a string, so a JSON `true` arrives as `True` and `null` as `None`. Ask researchers to send strings and parse them yourself. You cannot set the names in the table above from `spec.env`, so a researcher cannot override them.

There is no `DB_HOST`, `DB_PORT` or `DB_NAME`: use the connection string.


## CONNECTION_STRING format

The string is an ODBC connection string. Its format depends on the dataset's type:

**PostgreSQL** (`postgres`):
```
driver={PostgreSQL ANSI};Uid=<user>;Pwd=<password>;Server=<host>,<port>;Database=<name>;
```

**Microsoft SQL Server** (`mssql`):
```
driver={ODBC Driver 18 for SQL Server};Uid=<user>;Pwd=<password>;Server=<host>,<port>;Database=<name>;
```

**MySQL** (`mysql`):
```
driver={MySQL ODBC 9.3 ANSI Driver};Uid=<user>;Pwd=<password>;Server=<host>,<port>;Database=<name>;
```

**MariaDB** (`mariadb`):
```
driver={MariaDB ODBC 3.2 Driver};Uid=<user>;Pwd=<password>;Server=<host>,<port>;Database=<name>;
```

**Oracle** (`oracle`):
```
driver={Oracle ODBC Driver};Uid=<user>;PSW=<password>;DBQ=<host>:<port>/<name>;
```

The `extra_connection_args` field of a dataset is not added to the string. If your analysis needs extra connection options, add them yourself.

Using it with `pyodbc`:

```python
import os
import pyodbc

conn = pyodbc.connect(os.environ["CONNECTION_STRING"])
cursor = conn.cursor()
cursor.execute(f"SELECT * FROM {os.environ['CDM_SCHEMA']}.person LIMIT 10")
rows = cursor.fetchall()
```


## Writing results

Write every output file under `ARTIFACT_PATH`. When the task succeeds, the node zips that folder as `results.zip` and pushes it to the project's results repository as a pull request, together with the researcher's spec and a `run.json`. See [Researcher guide](./Researcher-Guide#4-get-your-results) for the layout.

```python
import json
import os

out = os.environ["ARTIFACT_PATH"]
with open(os.path.join(out, "summary.json"), "w") as f:
    json.dump({"patients": 1234, "mean_age": 7.4}, f)
```

- The zip can be at most **10 MiB** by default. Over that, the delivery fails, so write summaries, not extracts.
- **Symbolic links** in the folder are skipped.
- A person reads the results pull request before it is merged, so name files so that a reviewer can tell what they are.
- Anything your container prints to stdout or stderr shows in the Dagster run's logs, which the node admin can read. It is not part of the results. If you want a log with the results, write it to a file in `ARTIFACT_PATH`.

If your analysis writes results back into the database, it goes to `WRITE_SCHEMA`, which must already exist with write rights for the dataset's user.


## Exit status

Exit **0** when the analysis succeeded. Any other exit status marks the task `FAILED`, and **nothing is delivered**: the results folder of a failed task is not pushed. The container's own logs are the place to say why.


## What the pod is and is not allowed to do

The pod runs next to your data and runs an image the node's operators did not write, so it is locked down:

| Area | What it means for your container |
|---|---|
| **User** | Runs non-root as uid and gid 1001 by default, whatever the image's `USER` says. No privilege escalation, all Linux capabilities dropped. Do not write anywhere but `ARTIFACT_PATH` and temporary folders. |
| **Storage** | Only its own run's folder is mounted. It cannot see other runs' results. |
| **Network** | DNS and the dataset database only. No internet, no other services, no node API, no git. |
| **Kubernetes** | No service account token and no access to the Kubernetes API or any other secret. |
| **Time** | A pod is stopped after a deadline (6 hours by default). It then gets 300 seconds to exit, so flush your files when you receive the termination signal. |
| **CPU and memory** | The node's defaults, or what the spec's `compute` asks for, up to the node's maximum. |
| **Image** | Pulled on every run, so a re-pushed tag is picked up. The spec has no field for registry credentials: use an image the cluster can pull as it is, and ask your admin if you need a private one. |

The design is [ADR 0022](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/project/decisions/0022-task-isolation.md). The dataset database is only reachable if the operator has listed it in the chart's `taskNetworkPolicy.datasetEgress`: if your container hangs on connecting, start there ([Deploy: Core](./Deploy-Core#let-tasks-reach-their-dataset)).


## Changed from 1.x

| In 1.x | In 2.x |
|---|---|
| `DB_USER`, `DB_PSW` | `DB_USERNAME`, `DB_PASSWORD` |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_SCHEMA`, `DB_ARGS`, `ORACLE_SID` | Gone. Use `CONNECTION_STRING`. The read schema is `CDM_SCHEMA` |
| Results written to `/mnt/data` | Results written to `$ARTIFACT_PATH` |
| `INPUT_PATH`, `DATASET_TYPE`, `DATASET_PATH` (file datasets, pre-fetch) | Gone. DuckDB and SQLite datasets are not in the beta |
| `env` in `executors[0]` of the API request | `spec.env` in the task spec file |
| Image from a registered registry | The image named in the spec, pulled as it is |


## Testing your image

- **On your machine**, run the image with the variables above set by hand against a test database, and a folder as `ARTIFACT_PATH`.
- **For a real task**, ask your admin for a project, and follow the [Researcher guide](./Researcher-Guide).
