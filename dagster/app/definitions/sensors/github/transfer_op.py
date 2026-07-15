"""GitHub results transfer operation - pushes results back to GitHub."""

import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx

from app.github import GithubAPI
from app.config import GithubTransferConfig


class GithubTransferOperation:
    """Transfer experiment results back to GitHub."""

    def __init__(self, context: OpExecCtx, github_api: GithubAPI, config: GithubTransferConfig):
        self.context = context
        self.log = context.log
        self.github_api = github_api
        self.config = config

    def __call__(self) -> dg.Output:
        """Execute the transfer operation."""
        pr_number, parent_run_id, repo_uri = self._extract_config()
        trigger_owner, trigger_repo = self._parse_repo_uri(repo_uri)
        delivery_owner, delivery_repo = self._parse_repo_uri(
            self.config.delivery_repo
        )
        branch = f"{pr_number}-{parent_run_id}-results"

        self.log.info(
            f"GitHub transfer starting - PR#{pr_number}, run {parent_run_id}, "
            f"from {trigger_owner}/{trigger_repo} to {delivery_owner}/{delivery_repo}"
        )

        clone_dir = tempfile.mkdtemp(prefix="phems-transfer-")
        try:
            self._setup_repo(clone_dir, branch, delivery_owner, delivery_repo)
            self._archive_results(
                clone_dir, pr_number, parent_run_id, trigger_owner, trigger_repo
            )
            self._commit_and_push(clone_dir, pr_number, parent_run_id, branch)
            pr_url = self._create_results_pr(
                branch, pr_number, parent_run_id, trigger_owner, trigger_repo,
                delivery_owner, delivery_repo
            )
        finally:
            shutil.rmtree(clone_dir, ignore_errors=True)

        return dg.Output(
            value={"pr_url": pr_url, "branch": branch},
            metadata={"pr_url": pr_url, "branch": branch},
        )

    def _extract_config(self) -> tuple[str, str, str]:
        """Extract config from context."""
        return (
            self.context.op_config["pr_number"],
            self.context.op_config["parent_run_id"],
            self.context.op_config["repo_uri"],
        )

    def _parse_repo_uri(self, repo_uri: str) -> tuple[str, str]:
        """Parse owner and repo from GitHub URI."""
        # Handle both formats: https://github.com/owner/repo or owner/repo
        if repo_uri.startswith("https://"):
            parts = repo_uri.split("/")
            return parts[-2], parts[-1]
        else:
            owner, repo = repo_uri.split("/", 1)
            return owner, repo

    def _setup_repo(
        self, clone_dir: str, branch: str, delivery_owner: str, delivery_repo: str
    ) -> None:
        """Clone delivery repo and setup results branch."""
        clone_url = (
            f"https://{self.config.token}@github.com/"
            f"{delivery_owner}/{delivery_repo}.git"
        )
        delivery_full = f"{delivery_owner}/{delivery_repo}"
        self.log.info(f"Cloning delivery repo {delivery_full}")
        _git(["clone", "--depth=1", clone_url, clone_dir])
        _git(["-C", clone_dir, "config", "user.name", "phems-bot"])
        _git(
            [
                "-C",
                clone_dir,
                "config",
                "user.email",
                "phem-federated-node@users.noreply.github.com",
            ]
        )
        _git(["-C", clone_dir, "fetch", "origin"])

        if self.github_api.branch_exists(delivery_full, branch):
            raise Exception(
                f"Results branch {branch!r} already exists on remote"
            )

        _git(["-C", clone_dir, "checkout", "-b", branch])

    def _archive_results(
        self,
        clone_dir: str,
        pr_number: str,
        parent_run_id: str,
        trigger_owner: str,
        trigger_repo: str,
    ) -> Path:
        """Archive results into delivery repo, organized by trigger repo."""
        repo_output_path = (
            f"{self.config.results_dir}/{trigger_owner}/{trigger_repo}/"
            f"{pr_number}/{parent_run_id}"
        )
        artifact_path = (
            Path(self.config.artifact_mount_path) / parent_run_id
        )

        output_dir = Path(clone_dir) / repo_output_path
        output_dir.mkdir(parents=True, exist_ok=True)

        self.log.info(f"Archiving {artifact_path}")
        _zip_dir(artifact_path, output_dir / "archive.zip")

        return artifact_path

    def _commit_and_push(
        self, clone_dir: str, pr_number: str, parent_run_id: str, branch: str
    ) -> None:
        """Commit and push results branch."""
        _git(["-C", clone_dir, "add", "."])
        _git(
            [
                "-C",
                clone_dir,
                "commit",
                "-m",
                f"PR{pr_number} - {parent_run_id} - results",
            ]
        )
        _git(["-C", clone_dir, "push", "--set-upstream", "origin", branch])
        self.log.info("Results branch pushed")

    def _create_results_pr(
        self,
        branch: str,
        pr_number: str,
        parent_run_id: str,
        trigger_owner: str,
        trigger_repo: str,
        delivery_owner: str,
        delivery_repo: str,
    ) -> str:
        """Create pull request in delivery repo for results."""
        title = f"Results for {trigger_owner}/{trigger_repo} PR #{pr_number}"
        body = (
            f"Automated results for PR #{pr_number} in {trigger_owner}/{trigger_repo}\n"
            f"Run ID: {parent_run_id}"
        )
        delivery_full = f"{delivery_owner}/{delivery_repo}"
        pr_url = self.github_api.create_pull_request(
            delivery_full,
            branch,
            self.config.base_branch,
            title,
            body,
        )
        self.log.info(f"Pull request created: {pr_url}")
        return pr_url


def _git(args: list[str], cwd: str | None = None) -> None:
    """Execute a git command."""
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True)


def _zip_dir(src: Path, dest_zip: Path) -> None:
    """Zip a directory into a file."""
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in src.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(src))
