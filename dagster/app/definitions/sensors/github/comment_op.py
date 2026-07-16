"""GitHub PR comment operation."""

from dagster import OpExecutionContext as OpExecCtx

from app.github import GithubAPI


class GithubCommentOperation:
    """Add success comment to original PR."""

    def __init__(self, context: OpExecCtx, github_api: GithubAPI):
        self.context = context
        self.log = context.log
        self.github_api = github_api

    def __call__(self):
        """Execute the comment operation."""
        pr_number = int(self.context.op_config["pr_number"])
        parent_run_id = self.context.op_config["parent_run_id"]
        repo_uri = self.context.op_config["repo_uri"]

        # Parse owner/repo from full URI
        if repo_uri.startswith("https://"):
            parts = repo_uri.rstrip("/").split("/")
            repo_path = f"{parts[-2]}/{parts[-1]}"
        else:
            repo_path = repo_uri

        body = f"✅ Analysis complete - Run ID: {parent_run_id}"
        self.log.info(f"Adding comment to PR #{pr_number} in {repo_path}")
        self.github_api.add_pull_request_comment(repo_path, pr_number, body)
