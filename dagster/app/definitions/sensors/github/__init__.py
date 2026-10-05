import dagster as dg
from dagster import OpExecutionContext as OpExecCtx

from app.github import GithubAPI, GithubClient
from app.config import GithubTransferConfig, GithubConfig
from app.definitions.sensors.github.transfer_op import GithubTransferOperation
from app.definitions.sensors.github.comment_op import GithubCommentOperation


@dg.op(
    config_schema={
        "parent_run_id": dg.Field(str),
        "pr_number": dg.Field(str),
        "repo_uri": dg.Field(str),
    },
)
def github_transfer_op(context: OpExecCtx):
    """Transfer results to GitHub."""
    github_config = GithubConfig()
    github_api = GithubAPI(GithubClient(github_config.token, base_uri=github_config.base_uri))
    operation = GithubTransferOperation(context, github_api, GithubTransferConfig())
    return operation()


@dg.job
def github_transfer_job():
    """Job to transfer results back to GitHub."""
    github_transfer_op()


@dg.op(
    config_schema={
        "pr_number": dg.Field(str),
        "parent_run_id": dg.Field(str),
        "repo_uri": dg.Field(str),
    },
)
def github_pr_comment_op(context: OpExecCtx):
    """Add success comment to original PR."""
    github_config = GithubConfig()
    github_client = GithubClient(
        token=github_config.token,
        base_uri=github_config.base_uri
    )
    github_api = GithubAPI(github_client)
    operation = GithubCommentOperation(context, github_api)
    return operation()


@dg.job
def github_pr_comment_job():
    """Job to add success comment to original PR."""
    github_pr_comment_op()


SENSORS = []

JOBS = [github_transfer_job, github_pr_comment_job]
