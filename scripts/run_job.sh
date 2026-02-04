#!/usr/bin/env bash
set -euo pipefail

JOB_NAME="k8s_pipes_job"
IMAGE="localhost:5001/dagster-pipes-julia:v19"
DAGSTER_GRAPHQL_API="http://localhost:3000/graphql"

curl -X POST $DAGSTER_GRAPHQL_API \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"mutation { launchPipelineExecution(executionParams: { selector: { jobName: \\\"$JOB_NAME\\\", repositoryName: \\\"__repository__\\\", repositoryLocationName: \\\"dagster-fn\\\" }, runConfigData: { ops: { k8s_pipes_op: { config: { image: \\\"$IMAGE\\\" } } } } }) { __typename ... on LaunchPipelineRunSuccess { run { runId } } ... on PythonError { message } } }\"}"

echo