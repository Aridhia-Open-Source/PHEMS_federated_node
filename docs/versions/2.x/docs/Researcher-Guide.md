# Researcher Guide

This guide is for researchers who want to run an analysis on a Federated Node 2.x. You do not call the node to start a task. You write a small JSON file, add it to the project's trigger repository in a pull request, and when someone at the institution merges it, the node runs your container next to the data. The results come back as another pull request.

Before you start, ask the node's admin for:

- the **trigger repository**, its **watch directory** and its **base branch** (where your spec file goes);
- the **name of the dataset** you may use, or whether the project has a default;
- where the **results repository** is, so you can find your results.

You also need a container image that follows the [container contract](./Analytics-Container-Development), pushed somewhere the cluster can pull it from.


## 1. Write the task spec

The spec file says what to run. Only `spec` and `metadata` are allowed at the top level, and `spec` is required:

```json
{
  "spec": {
    "image": "ghcr.io/your-org/your-analytics-image:1.0",
    "dataset": "my-dataset",
    "env": {"COHORT": "paediatric", "MIN_AGE": "0"},
    "tags": {"team": "analytics"},
    "config": {"epochs": 3},
    "compute": {
      "requests": {"cpu": "500m", "memory": "1Gi"},
      "limits": {"cpu": "2", "memory": "4Gi"}
    }
  },
  "metadata": {"ticket": "ABC-1"}
}
```

| Field | Required | What it does |
|---|---|---|
| `spec.image` | yes | The container image to run, up to 256 characters. |
| `spec.dataset` | no | The name of a dataset your project has and that is switched on. Without it, the project's default dataset is used, if it has one. |
| `spec.env` | no | Environment variables for your container. See below. |
| `spec.tags` | no | Text labels copied onto the task's run. |
| `spec.config` | no | A JSON object your container reads as a file, at the path in `CONFIG_PATH`. Its contents are not checked. |
| `spec.compute` | no | The CPU and memory to ask for: `requests` and `limits`, each with an optional `cpu` and `memory`. |
| `metadata` | no | Yours: any JSON, not checked, kept with the task and delivered with the results. |

Any other field, at either level, makes the pull request `REJECTED`.

**`env`:**

- A name matches `^[A-Za-z_][A-Za-z0-9_]*$` and arrives upper-cased.
- Values reach your container as text. Send strings: a JSON `true` arrives as `True`.
- You cannot set `ARTIFACT_PATH`, `CDM_SCHEMA`, `WRITE_SCHEMA`, `DB_USERNAME`, `DB_PASSWORD`, `CONNECTION_STRING` or `CONFIG_PATH`, or any name starting with `DAGSTER_` or `KUBERNETES_`, in any letter case. The node sets those itself.
- All of `env`, as JSON, is at most 32 KiB.

**`tags`:** a key is 1 to 63 letters, digits, `_`, `.` or `-` (so no `/`), and a value is text.

**`compute`:** values are Kubernetes quantities (`500m`, `2`, `512Mi`, `4Gi`). A limit cannot be lower than its request, and nothing can be over the node's maximum. A request with no limit of its own cannot be over the node's default limit. Without `compute`, the node's defaults apply. Ask your admin for the numbers (`taskCompute` in the chart).

The whole file is at most 64 KiB. The exact rules are in the [spec schema](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/docs/schemas/spec.schema.json), which your editor can use to check the file.


## 2. Open and merge the pull request

1. In the trigger repository, on a branch, add the spec file under the **watch directory**, for example `specs/first-task.json`.
2. Open a pull request into the **base branch**.
3. Someone with merge rights merges it. **Only merged pull requests are read.**

What the node does with a merged pull request:

| The pull request | Result |
|---|---|
| Adds exactly one `.json` file under the watch directory, with a valid spec | A task is created |
| Adds more than one `.json` file under the watch directory | `REJECTED`: "Several new spec files" |
| Adds one, but the spec is not valid | `REJECTED`, with the reason |
| Adds no `.json` file under the watch directory, or goes to another branch | Ignored: no task, no error |
| Was merged before your project was enabled | Ignored, unless the admin asked for a backfill |

Only **added** files count. Changing or deleting a spec file does nothing, and editing a spec after it is merged changes nothing: the task keeps the spec as read at the merge. To run again with changes, add a new file in a new pull request.

The task is named `<project name>:PR#<pull request number>`.


## 3. Wait for the task

The node checks for new pull requests every 30 seconds or so, then queues the task and starts a pod. The task goes through `PENDING`, `QUEUED`, `RUNNING` and then `SUCCESS` or `FAILED` (`CANCELED` if it is stopped). Your admin can see the run and its logs in Dagster, and can read the task through the API (`GET /projects/<id>/tasks`).

If nothing seems to happen after a few minutes, the usual causes are on the admin's side: the sensors are stopped, the project or one of its resources is switched off, or your pull request was one of the ignored kinds above. A rejected pull request or a task that cannot start has its reason in `state_cause`.

A task that **fails** delivers nothing. The container must exit with status 0 to succeed.


## 4. Get your results

When the task succeeds, the node pushes the results to the project's results repository and opens a **results pull request** from a new branch into the project's results `base_branch`. Under the project's `target_dir`, the branch and the files are laid out like this:

```
<target_dir>/<trigger repository name>/<pr number>/<task id>/
    results.zip     everything your container wrote to ARTIFACT_PATH
    spec.json       your spec file, byte for byte (so your metadata rides along)
    run.json        the node, project, trigger, task and delivery details
```

The branch is named `<target_dir>/<trigger repository name>/<pr number>/<task id>-<merge commit sha, first 7>`.

The `results.zip` can be at most 10 MiB (the node's setting `fnDagster.results.maxZipBytes`). Over that, the delivery fails. Symbolic links in your output are skipped. The structure of `run.json` is in the [run schema](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/beta/docs/schemas/run.schema.json).

The results pull request is the review step. Someone at the institution reads it, and merging it releases the results. Closing it without merging does not. The node records which happened.

The outcome is not commented back on your trigger pull request, so look in the results repository.


## Trying it

On a development node with the chart's Gitea, `fncli open-pr --merge` opens and merges a sample pull request for you. The spec file it commits has the format described here.
