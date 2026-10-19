# 0021. Responsibility: the webserver owns the record and the rules; Dagster carries out decisions

## Context

Dagster polls, starts runs and watches them; the webserver stores the state. Rules about what may run, such as whether a dataset link is active, could be written on either side. A rule held in both drifts, and a rule held in Dagster cannot be tested or changed with the data it reads.

## Decision

- The webserver owns the record and every rule. It is the only writer of the state, through its state tables ([0005](0005-state-transition-tables.md)).
- Dagster owns doing the work: polling, starting runs, watching them, and git. It holds no copy of the rules.
- Dagster asks and acts; it does not decide. Facts go from Dagster to the webserver (a run started, a run failed) and decisions come back as typed outcomes: launch, wait or fail, with a cause for fail. A status code means only whether the call worked, never what was decided.
- A call repeated each tick is safe: a decision is computed read-only from the current state, and a write that repeats is refused or ignored by the state tables.
- The dependency is one way: Dagster calls the webserver; the webserver never calls Dagster.

The task launcher follows it. `GET /projects/<id>/tasks/<id>/config` returns `outcome` (`launch` or `fail`) and `cause`, computed by `decide_launch` in `webserver/app/helpers/task_config.py`. The first rule that applies decides, in this order: something the task uses is revoked or deleted, its pinned configuration changed ([0009](0009-task-pinned-to-its-configuration.md)), its dataset link is not active, its dataset's secret is disabled ([0008](0008-enabled-revoked-and-soft-delete.md)). The launcher patches the task `FAILED` with the cause on `fail` and builds the run request otherwise; it checks nothing itself.

## Consequences

- A rule changes in one place, with its tests next to the data it reads.
- The launcher's tests mock the answer and check that it does what the outcome says.
- The launcher still reads the dataset to build the run configuration; that is data, not a rule.
- Each tick costs the webserver the rule queries for every pending task.

## Alternatives considered

- **Rules in the launcher, reading facts from several endpoints:** the rules drift from the record and are tested against mocks.

## Open questions

- Delivery should follow the same pattern: a deliver decision from the webserver, with Dagster pushing and reporting.
- A full launch endpoint that decides and moves the task under a row lock, so the decision and the write cannot be separated, is a possible next step.
