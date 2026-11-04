from typing import cast

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx

from app.backend import BackendAPI
from app.definitions.sensors.git.base import GitAPI, GitAPIFactory
from app.models import NewPullRequest, TriggerRepository

# The most pull requests the backend takes in one ingest
MAX_BATCH_SIZE = 100


def fetch_pull_request(git_api: GitAPI, repo: TriggerRepository, pr_number: int) -> NewPullRequest:
    """The pull request and the files it changed, which the backend matches against each watcher's watch_dir."""
    pr = git_api.get_pull_request(repo.repo_path, pr_number)
    files = git_api.get_pull_request_files(repo.repo_path, pr_number)
    # A duplicate path would make the backend 500 the whole batch (pull_request_files primary key)
    unique_files = list({f["filename"]: f for f in files}.values())
    return NewPullRequest.from_git(pr, unique_files)


@dg.op(config_schema={"repo_id": dg.Field(int)}, required_resource_keys={"backend_api", "git_apis"})
def ingest_pull_requests(context: OpExecCtx):
    """
    Posts the PRs merged on the repository since its cursor, the latest stored merge or, with
    none stored, the repository's creation, in batches of at most MAX_BATCH_SIZE, oldest
    first: the cursor only moves once a batch is stored, so a batch never leaves an older
    unposted PR behind it. The repository is read again, so the cursor is the current one.
    """
    backend_api = cast(BackendAPI, context.resources.backend_api)
    git_apis = cast(GitAPIFactory, context.resources.git_apis)
    repo = backend_api.get_trigger_repository(context.op_config["repo_id"])
    git_api = git_apis.for_repository(repo)

    context.log.info(f"Fetching PRs for {repo.repo_path} since {repo.pr_cursor}")
    merged = git_api.get_new_merged_pulls(repo_path=repo.repo_path, merged_after=repo.pr_cursor)
    context.log.info(f"Git provider returned {len(merged)} PRs for {repo.repo_path}")

    pull_requests = sorted(
        (fetch_pull_request(git_api, repo, pr["number"]) for pr in merged), key=lambda pr: (pr.merged_at, pr.number)
    )
    for start in range(0, len(pull_requests), MAX_BATCH_SIZE):
        batch = pull_requests[start:start + MAX_BATCH_SIZE]
        context.log.info(f"Saving batch of {len(batch)} PRs for repo {repo.id}")
        backend_api.create_pull_requests_batch(repo.id, [pr.model_dump() for pr in batch])
    context.log.info(f"Saved {len(pull_requests)} new pull requests of {repo.uri}")


@dg.job
def ingest_pull_requests_job():
    """
    Ingest the new merged pull requests of one global trigger repository (run config: repo_id).
    Its tags are fn/trigger=ingest and fn/repo_id, never fn/trigger=task: the run-status sensors act on that.
    """
    ingest_pull_requests()  # pylint: disable=no-value-for-parameter  # Dagster injects context
