# Datasets

A dataset tells the Federated Node where a research database lives and how a task connects to it. The node stores the connection details. It never copies or centralises the data.

This page covers the database types a node supports, how to register one, what each field does, how a project gets to use it, and what changes when you edit or switch it off. Registering, editing and deleting datasets is an admin job.

Every example assumes `$FN` is your node's address and `${AUTH[@]}` is an admin's bearer token header, as set up in [Using the API](./Using-The-API#authentication).


## How datasets fit in

A dataset is a **global resource**: an admin registers it once, and then **assigns** it to each project that may use it. A task runs against one dataset, which is:

- the dataset named in the task spec's `dataset` field, if it is assigned to the project and switched on; or
- the project's **default dataset**, if the spec names none. The first dataset assigned to a project becomes its default.

The task's container is given the database login and the schema names as environment variables ([Analytics container development](./Analytics-Container-Development)). The dataset's credentials never appear in the spec or in the API.


## Supported dataset types

A dataset is always a database server the node connects to over the network.

| `type` | Database | ODBC driver in `CONNECTION_STRING` | Healthcheck |
|---|---|---|---|
| `postgres` (the default) | PostgreSQL | `PostgreSQL ANSI` | yes |
| `mssql` | Microsoft SQL Server | `ODBC Driver 18 for SQL Server` | yes |
| `mysql` | MySQL | `MySQL ODBC 9.3 ANSI Driver` | no |
| `mariadb` | MariaDB | `MariaDB ODBC 3.2 Driver` | no |
| `oracle` | Oracle | `Oracle ODBC Driver` | no |

Any other `type` is refused with `DB type <type> is not supported.`

### ODBC drivers

The task connects with the ODBC driver in the table, so the **analytics container needs that driver installed**. The FN task base images, `python-base` and `r-base`, include all five ([Federated-Node-Task-Base-Images](https://github.com/Aridhia-Open-Source/Federated-Node-Task-Base-Images)). If you build on another base image, install the driver yourself. The exact connection string for each type is in [Analytics container development](./Analytics-Container-Development#connection_string-format).

File datasets (DuckDB, SQLite) are not yet supported.


## Dataset fields

| Field | Required | Description |
|---|---|---|
| `name` | yes | The **database name** on that host, not a display label. Stored lowercase. Names are unique across the node (a taken name is a `409`). This is also the name researchers use in `spec.dataset`. |
| `host` | yes | The database host name or address. |
| `port` | yes | The database port, as a number between 1 and 65535. There is **no default**: set it for every type, including PostgreSQL (`5432`), SQL Server (`1433`), MySQL and MariaDB (`3306`) and Oracle (`1521`). |
| `secret_label` | yes | The label of the global secret that holds the database login, with the keys `USERNAME` and `PASSWORD`. It must exist and be switched on. |
| `type` | no | One of the types above. Defaults to `postgres`. |
| `read_schema` | no | The schema tasks read from. Given to the task as `CDM_SCHEMA`. |
| `write_schema` | no | The schema tasks may write results into. Given as `WRITE_SCHEMA`. It must already exist, with write rights for the dataset's user. |
| `extra_connection_args` | no | Extra connection text, up to 4096 characters, stored with the dataset. It is **not** added to the task's connection string today: see [Connection options](#connection-options). |
| `enabled` | no | Defaults to `true`. |
| `catalogue`, `dictionaries` | no | A description of the data. See [Catalogue and dictionaries](#catalogue-and-dictionaries). |

Field types are strict: `port` must be a number, not `"5432"`, and `enabled` a boolean. `revoked` is not accepted on create: an admin revokes a dataset with a `PATCH`.

`username`, `password` and `project_id` are refused with a message saying what to do instead: credentials go in a secret, and a dataset is assigned to a project afterwards.

**Create ignores fields it does not know.** A misspelled field still returns `201`, with that value unset. Read the dataset back to check it. (`PATCH` is stricter: it refuses unknown fields.)


## Register a dataset

### 1. Store the database login

Create a global secret. The keys must be `USERNAME` and `PASSWORD`:

```sh
curl -sS -X POST "$FN/global/secrets" "${AUTH[@]}" -d '{
  "label": "omop-creds",
  "provider": "K8S",
  "values": {"USERNAME": "fn_reader", "PASSWORD": "<db password>"}
}' | jq
```

Use a dedicated, read-only database account scoped to exactly the schema you intend to expose, not an application or admin account. The secret is stored in Kubernetes. The database keeps only a reference, and no call returns the values.

### 2. Register the dataset

Every type uses the same request. Only `type`, `port` and the schemas change.

**PostgreSQL**

```sh
curl -sS -X POST "$FN/global/datasets" "${AUTH[@]}" -d '{
  "name": "omop_cdm",
  "host": "postgres.your-institution.example.com",
  "port": 5432,
  "type": "postgres",
  "secret_label": "omop-creds",
  "read_schema": "cdm",
  "write_schema": "results"
}' | jq
```

**Microsoft SQL Server**

```sh
curl -sS -X POST "$FN/global/datasets" "${AUTH[@]}" -d '{
  "name": "omop_cdm",
  "host": "mssql.your-institution.example.com",
  "port": 1433,
  "type": "mssql",
  "secret_label": "omop-creds",
  "read_schema": "dbo"
}' | jq
```

**MySQL and MariaDB**

```sh
curl -sS -X POST "$FN/global/datasets" "${AUTH[@]}" -d '{
  "name": "omop_cdm",
  "host": "mysql.your-institution.example.com",
  "port": 3306,
  "type": "mysql",
  "secret_label": "omop-creds",
  "read_schema": "omop_cdm"
}' | jq
```

For MariaDB, set `"type": "mariadb"`. These engines have no separate schema level (a schema is a database), so `read_schema` is usually the same as `name`.

**Oracle**

```sh
curl -sS -X POST "$FN/global/datasets" "${AUTH[@]}" -d '{
  "name": "orclpdb1",
  "host": "oracle.your-institution.example.com",
  "port": 1521,
  "type": "oracle",
  "secret_label": "omop-creds",
  "read_schema": "CDM"
}' | jq
```

For Oracle, `name` is the **service name**: the connection string uses `DBQ=<host>:<port>/<name>`.

The response is the new dataset, with its `id`, `slug`, `url`, `enabled` and `revoked` flags, and the secret it uses (never its values). Keep the `id`: assigning and managing the dataset use it.

### Connection options

The connection string the task gets is built from `host`, `port`, `name` and the login, and nothing else. `extra_connection_args` is not appended. If your database needs more options, add them in your analysis code. For SQL Server, ODBC Driver 18 encrypts by default and validates the server's certificate, so a server with a self-signed certificate needs `TrustServerCertificate=yes;` added to the string by the analysis. A server whose certificate your container trusts needs nothing.


## Check it works

```sh
curl -sS "$FN/global/datasets/$DATASET_ID/healthcheck" "${AUTH[@]}" | jq
```

This logs in to the database with the stored credentials and runs a trivial query, so you find out now and not when the first task fails. A failure shows in the body, with a status of 200 and no secret values. Only PostgreSQL and SQL Server datasets can be checked: for the other types the check reports that it cannot be done, which is not a fault in the dataset. `GET /global/healthcheck` checks every dataset at once.

Three more things must be right before a task can reach the database:

- The cluster's network policy must allow task pods to reach it. Databases on private addresses (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) are allowed by default. For any other address, **add the database to `taskNetworkPolicy.datasetEgress`** in the chart values ([Deploy: Core](./Deploy-Core#let-tasks-reach-their-dataset)). Without that, tasks time out on connecting.
- The database login must be able to read `read_schema` and, if tasks write, `write_schema`.
- The analytics image must have the ODBC driver for the dataset's type (see above).

Then assign it to a project: `PUT /projects/<project id>/datasets/<dataset id>`. The body is optional and may hold `{"enabled": true}`.


## Managing datasets

### List and read

```sh
curl -sS "$FN/global/datasets" "${AUTH[@]}" | jq
curl -sS "$FN/global/datasets/$DATASET_ID" "${AUTH[@]}" | jq
```

The list is paginated. A dataset is read by its numeric `id`.

### Update

`PATCH` only the fields you want to change. At least one is needed, and a field the dataset does not have is refused.

```sh
curl -sS -X PATCH "$FN/global/datasets/$DATASET_ID" "${AUTH[@]}" -d '{"write_schema": "results_v2"}' | jq
```

A task is **pinned** to the configuration it was created with. The dataset's host, port, type and schemas are copied into each task when it is created, and the node checks before launch that they still hold. If you change them, tasks created earlier that have not started yet fail, with a message saying what changed.

To switch a dataset to another login, send a new `secret_label`. To rotate the password, write the secret again: `PATCH /global/secrets/<label>` with `{"values": {"USERNAME": "...", "PASSWORD": "..."}}`. It reaches work already running.

### Switch it off

| To stop | Do this |
|---|---|
| One project using the dataset | `PATCH /projects/<id>/datasets/<dataset id>` with `{"enabled": false}` |
| Every project using it | `PATCH /global/datasets/<id>` with `{"enabled": false}` (or `{"revoked": true}`, admin only) |
| Its login | Switching off the secret (`PATCH /global/secrets/<label>`) also switches off the datasets and repositories that use it |

A pending task whose dataset is switched off does not start, and its `state_cause` says why. Turning a dataset back on is refused with a `409` while its secret is switched off or deleted. [Operations](./Operations#switch-things-on-and-off) has the full list of switches.

### Delete

`DELETE /global/datasets/<id>` is a **soft delete**: the dataset disappears from the API and the name is free again, but the record stays for the tasks and results that used it. If projects still use the dataset, the delete is refused with a `409` that lists them. Add `?force=true` to revoke and remove those project resources too. The dataset's secret is left alone, because other datasets may share it. Prefer switching a dataset off.

### Catalogue and dictionaries

You can describe a dataset when you register it or later, so people know what is in it without seeing the data. Send them in the same body:

```json
{
  "catalogue": {
    "title": "OMOP CDM extract",
    "description": "Inpatient episodes 2018-2025",
    "version": "5.4"
  },
  "dictionaries": [
    {
      "table_name": "person",
      "field_name": "year_of_birth",
      "label": "Year of birth",
      "description": "Patient year of birth"
    }
  ]
}
```

`title` and `description` are required in a catalogue, `version` is optional. A dictionary entry needs `table_name`, `field_name` and `description`, and may have a `label`. A `PATCH` updates the catalogue, and adds or updates the entries it names. They are stored with the dataset, but no route returns them yet.


## Not yet supported

- File datasets (DuckDB, SQLite) and the volumes they read from.
- Fetching a query's result into the task before it starts. A task queries the database itself.
- Granting individual users access to a dataset.
- Appending `extra_connection_args` to the connection string.
- A healthcheck for MySQL, MariaDB and Oracle datasets.


## Troubleshooting

| Error or symptom | Cause |
|---|---|
| `400` `username and password are not accepted` | The login goes in a secret. Create it with `POST /global/secrets` and pass `secret_label`. |
| `400` `project_id is not accepted` | Datasets are global. Assign one with `PUT /projects/<id>/datasets/<dataset id>`. |
| `400` `DB type ... is not supported.` | `type` is not one of the five above. |
| `400` `Invalid dataset: ...` | A required field is missing or has the wrong type, such as a `port` sent as a string. |
| `400` `Secret ... does not exist` or `is disabled` | `secret_label` names a secret that is missing or switched off. |
| `409` `Dataset ... already exists` | The name is taken, ignoring case. |
| `409` on delete | Projects still use the dataset. The response lists them. |
| A task times out connecting | The database is not reachable from the tasks namespace. Add it to `taskNetworkPolicy.datasetEgress`, and check the host and `port`. |
| A task cannot load the driver | The analytics image lacks the ODBC driver for the dataset's type. |
| Healthcheck says the dataset cannot be checked | The type is MySQL, MariaDB or Oracle. Run a task against it instead. |
| A pending task fails with a message about a changed dataset | The dataset was edited after the task was created. |
