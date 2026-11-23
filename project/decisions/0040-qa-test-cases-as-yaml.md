# 0040. QA test cases as YAML, set up and torn down through the operator

Status: Proposed, 2026-11-23.

## Context

- **The QA plan is manual.** `project/QA/` lists cases with steps and an expected result, and a person runs them by hand against a deployed node. Nothing says how to set a case up, run it again or clean up after it.
- **Testers do not write code.** A case should read like the plan: some resources, some steps, what is expected.
- **The operator changes setup.** Once node config is applied as Kubernetes resources (ADR 0032), setup is a set of resource files and teardown is deleting them; the operator and its finalizers do the rest.
- **A case is not only resources.** It also needs steps the operator does not do, such as opening a task pull request, waiting for the task and its results, and making API calls.

## Decision

- **A case is a YAML file** in `project/QA/cases/`: a name, `setup` (resource files to apply), `steps` and `teardown`. One file per case of the manual plan.
- **Setup and teardown go through the operator.** Setup applies the resource files and waits until they are synced. Teardown deletes them in reverse order and always runs, even when a step fails.
- **The test technology is not chosen.** The aim is a declarative, Kubernetes-oriented runner that applies, asserts and cleans up. The candidates are under Alternatives considered.
- **How a case opens a task pull request and waits for the task and its results pull request is TBD.**

## Consequences

- QA can add a case by copying one and editing it. Cases can run in CI against a kind cluster.
- Every case also exercises the operator path.
- Cases depend on the operator, so they cannot be written before it lands.
- Whichever tool is chosen is one more thing to learn and keep up to date.

## Alternatives considered

- **A declarative Kubernetes test runner** (Kyverno Chainsaw, or its older sibling KUTTL): apply, assert on resource status, automatic cleanup. A candidate, not a decision.
- **Tavern or Hurl:** YAML or plain-text HTTP tests with assertions. Nothing for Kubernetes resources.
- **Newman on the Postman collection:** fine for API-only cases, no setup or teardown of node config.
- **A runner of our own:** full control, more code to maintain.
- **Robot Framework or Gherkin:** friendlier to read, but another language for testers.

## Open questions

- Which technology?
- How are the steps outside Kubernetes expressed: the task pull request, the results and the API calls?
- Where do the example resources live: `config/` (as in the operator QA plan) or beside the cases?
- Which cases run in CI, and on which cluster?
