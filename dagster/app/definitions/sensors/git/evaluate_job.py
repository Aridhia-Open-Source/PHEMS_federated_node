from http import HTTPStatus
from typing import cast

import dagster as dg
import requests
from dagster import OpExecutionContext as OpExecCtx

from app.backend import BackendAPI
from app.definitions.sensors.git.base import GitAPIFactory
from app.definitions.sensors.git.pr_parser import ParsedPullRequest, PullRequestOutcome, PullRequestParser
from app.models import PullRequest, TriggerState

# The git provider's API rate limit is the constraint, so keep the fan-out low
MAX_CONCURRENT_EVALUATIONS = 3


@dg.op(
    config_schema={"repo_id": dg.Field(int)},
    required_resource_keys={"backend_api"},
    out=dg.DynamicOut(PullRequest),
)
def load_unknown_pull_requests(context: OpExecCtx):
    """Emit the UNKNOWN pull requests of the repository, oldest first."""
    backend_api = cast(BackendAPI, context.resources.backend_api)
    pull_requests = backend_api.get_pull_requests(context.op_config["repo_id"], TriggerState.UNKNOWN.value)
    for pr in sorted(pull_requests, key=lambda p: p.merged_at):
        yield dg.DynamicOutput(pr, mapping_key=str(pr.number))


def record_outcome(backend_api: BackendAPI, pr: PullRequest, parsed: ParsedPullRequest, log):
    """
    Write the outcome on the pull request: READY becomes its task (the backend marks it
    YIELDED), IGNORED and REJECTED are stored with their state_cause. Backend failures raise.
    """
    repo_id = pr.trigger_repository_id
    if parsed.outcome is PullRequestOutcome.READY:
        try:
            backend_api.create_task_for_pull_request(repo_id, pr.number, parsed.spec.model_dump())
            return
        except requests.HTTPError as e:
            # The backend validates the spec again and rejects one it cannot run
            if e.response.status_code != HTTPStatus.BAD_REQUEST:
                raise
            log.error(f"PR #{pr.number} spec rejected by the backend: {e.response.text}")
            parsed = ParsedPullRequest(outcome=PullRequestOutcome.REJECTED, state_cause=e.response.text)

    backend_api.patch_pull_request(repo_id, pr.number, {"state": parsed.outcome.value, "state_cause": parsed.state_cause})


@dg.op(
    required_resource_keys={"backend_api", "git_apis"},
    retry_policy=dg.RetryPolicy(max_retries=3, delay=5, backoff=dg.Backoff.EXPONENTIAL),
)
def evaluate_pull_request(context: OpExecCtx, pr: PullRequest):
    """
    Read the spec of one UNKNOWN pull request and record its outcome. A bad spec is an
    outcome; only a git or backend failure raises, and the retry policy covers it.
    """
    backend_api = cast(BackendAPI, context.resources.backend_api)
    git_apis = cast(GitAPIFactory, context.resources.git_apis)
    repo = backend_api.get_repository(pr.trigger_repository_id)
    parsed = PullRequestParser(git_apis.for_repository(repo), repo, context.log).parse(pr)
    record_outcome(backend_api, pr, parsed, context.log)


@dg.job(executor_def=dg.multiprocess_executor.configured({"max_concurrent": MAX_CONCURRENT_EVALUATIONS}))
def evaluate_repository_pull_requests_job():
    """Evaluate the UNKNOWN pull requests of one repository (run config: repo_id)."""
    load_unknown_pull_requests().map(evaluate_pull_request)
