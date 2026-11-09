# Datasets

A dataset is a database that analytics tasks read from, and may write results into. This page covers how to register one on a Federated Node 2.x, how a project gets to use it, and what changes when you edit or switch it off.

DuckDB and SQLite file datasets from 1.x are not in the beta. A 2.x dataset is always a database the node connects to over the network.


## How datasets fit in

A dataset is a **global resource**: an admin registers it once, and then **assigns** it to each project that may use it. A task runs against one dataset, which is:

- the dataset named in the task spec's `dataset` field, if it is assigned to the project and switched on; or
- the project's **default dataset**, if the spec names none. The first dataset assigned to a project becomes its default.

The task's container is given the database login and the schema names as environment variables ([Analytics container development](./Analytics-Container-Development)). The dataset's credentials never appear in the spec or in the API.


## Register a dataset

First store the database login as a global secret, with the keys `USERNAME` and `PASSWORD`. Then register the dataset, as an admin:

```sh
curl -sS -X POST "$FN/global/datasets" "${AUTH[@]}" -d '{
  "name": "uc1_omop",
  "host": "db.your-institution.example.com",
  "port": 5432,
  "type": "postgres",
  "secret_label": "uc1-dataset-creds",
  "read_schema": "cdm",
  "write_schema": "results"
}' | jq
```

| Field | Description |
|---|---|
| `name` | The **database name** on that host (stored in lowercase), not a display label. Names are unique across the node. This is also the name researchers use in `spec.dataset`. |
| `host`, `port` | Where the database is. |
| `type` | `postgres` (the default), `mssql`, `mysql`, `mariadb` or `oracle`. |
| `secret_label` | The label of the secret holding `USERNAME` and `PASSWORD`. |
| `read_schema` | The schema tasks read from. Given to the task as `CDM_SCHEMA`. |
| `write_schema` | The schema tasks may write results into. Given as `WRITE_SCHEMA`. It must already exist, with write rights for the dataset's user. |
| `extra_connection_args` | Optional extra text stored with the dataset. It is not added to the task's connection string today. |

**Unknown fields are ignored.** A misspelled field still returns 201, with that value unset. Read the dataset back to check it:

```sh
curl -sS "$FN/global/datasets/$DATASET_ID" "${AUTH[@]}" | jq
```


## Check it works

```sh
curl -sS "$FN/global/datasets/$DATASET_ID/healthcheck" "${AUTH[@]}" | jq
```

This logs in to the database with the stored credentials, so you find out now and not when the first task fails. A failure shows in the body, with a status of 200 and no secret values.

Two more things must be right before a task can reach the database:

- The cluster's network policy must allow task pods to reach it. It is empty by default, so **add the database to `taskNetworkPolicy.datasetEgress`** in the chart values ([Deploy: Core](./Deploy-Core#let-tasks-reach-their-dataset)). Without that, tasks time out on connecting.
- The database login must be able to read `read_schema` and, if tasks write, `write_schema`.

Then assign it to a project: `PUT /projects/<project id>/datasets/<dataset id>`.


## Changing a dataset

A task is **pinned** to the configuration it was created with. The dataset's host, port, type and schemas are copied into each task when it is created, and the node checks before launch that they still hold. If you change them, tasks created earlier that have not started yet fail, with a message saying what changed.

To rotate the database password, write the secret again: `PATCH /global/secrets/<label>` with `{"values": {"USERNAME": "...", "PASSWORD": "..."}}`. It reaches work already running.


## Switching a dataset off

| To stop | Do this |
|---|---|
| One project using the dataset | `PATCH /projects/<id>/datasets/<dataset id>` with `{"enabled": false}` |
| Every project using it | `PATCH /global/datasets/<id>` with `{"enabled": false}` (or `{"revoked": true}`, admin only) |
| Its login | Switching off the secret (`PATCH /global/secrets/<label>`) also switches off the datasets and repositories that use it |

A pending task whose dataset is switched off does not start, and its `state_cause` says why. [Operations](./Operations#switch-things-on-and-off) has the full list of switches.

`DELETE /global/datasets/<id>` is a **soft delete**: the dataset disappears from the API and the name is free again, but the record stays for the tasks and results that used it. If projects still use the dataset, the delete is refused with a `409` that lists them. Prefer switching a dataset off.
