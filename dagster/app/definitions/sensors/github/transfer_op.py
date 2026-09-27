"""GitHub results transfer operation - pushes results back to Gitea."""

import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime as dt

import dagster as dg
from dagster import OpExecutionContext as OpExecCtx

from app.github import GithubAPI
from app.backend import BackendAPI
from app.config import GithubTransferConfig


class GithubTransferOperation:
    """Transfer experiment results to configured backend (git, s3, azure, gcp)."""

    def __init__(
        self,
        context: OpExecCtx,
        github_api: GithubAPI,
        backend_api: BackendAPI,
        config: GithubTransferConfig
    ):
        self.context = context
        self.log = context.log
        self.github_api = github_api
        self.backend_api = backend_api
        self.config = config

    def __call__(self) -> dg.Output:
        """Execute the transfer operation."""
        project_id, pr_number, parent_run_id, repo_uri = self._extract_op_config()
        self._setup_context(project_id, pr_number, parent_run_id, repo_uri)
        self._fetch_spec()

        self.log.info(f"Starting {self.project.results_backend.type} transfer: {self.run_dir_name}")

        try:
            self._setup_repo()
            self._handle_backend()
            pr_url = self._create_results_pr()
        finally:
            self._cleanup()

        return dg.Output(
            value={"pr_url": pr_url, "branch": self.branch},
            metadata={"pr_url": pr_url, "branch": self.branch},
        )

    def _extract_op_config(self) -> tuple[int, str, str, str]:
        """Extract config from Dagster op context."""
        return (
            self.context.op_config["project_id"],
            self.context.op_config["pr_number"],
            self.context.op_config["parent_run_id"],
            self.context.op_config["repo_uri"],
        )

    def _setup_context(self, project_id: int, pr_number: str, parent_run_id: str, repo_uri: str) -> None:
        """Extract and store all context as instance variables."""
        self.pr_number = pr_number
        self.parent_run_id = parent_run_id
        self.trigger_owner, self.trigger_repo = self._parse_repo_uri(repo_uri)
        self.delivery_owner, self.delivery_repo = self._parse_repo_uri(self.config.delivery_repo)

        self.run_dir_name = self._derive_run_dir_name(parent_run_id)
        self.branch = f"results-{self.run_dir_name}"
        self.artifact_path = Path(self.config.artifact_mount_path) / self.run_dir_name
        self.clone_dir = tempfile.mkdtemp(prefix="phems-transfer-")
        self.repo_output_path = self._build_repo_output_path()
        self.output_dir = Path(self.clone_dir) / self.repo_output_path

        self.project = self.backend_api.get_project(project_id)
        self.spec = None  # Will be populated by _fetch_spec()

    def _fetch_spec(self) -> None:
        """Fetch spec from PR or API request based on pr_number."""
        try:
            # Fetch task by parent_run_id to get the spec
            task = self.backend_api.get_task_by_run_id(self.parent_run_id)
            if task and task.trigger_payload:
                self.spec = task.trigger_payload
                self.log.info(f"Fetched spec: {task.trigger_payload}")
            else:
                self.log.warning(f"No task found for run {self.parent_run_id}")
        except Exception as e:
            self.log.warning(f"Could not fetch spec: {e}")

    def _derive_run_dir_name(self, parent_run_id: str) -> str:
        """Derive timestamp-uuid directory name."""
        timestamp_str = dt.utcnow().strftime("%Y%m%d-%H%M%S")
        return f"{timestamp_str}-{parent_run_id[:8]}"

    def _build_repo_output_path(self) -> str:
        """Build path to output directory in git repo."""
        return f"{self.config.results_dir}/{self.trigger_owner}/{self.trigger_repo}/{self.run_dir_name}"

    def _parse_repo_uri(self, repo_uri: str) -> tuple[str, str]:
        """Parse owner and repo from GitHub URI."""
        if repo_uri.startswith("https://"):
            parts = repo_uri.split("/")
            return parts[-2], parts[-1]
        else:
            owner, repo = repo_uri.split("/", 1)
            return owner, repo

    def _setup_repo(self) -> None:
        """Clone delivery repo and setup results branch."""
        delivery_full = f"{self.delivery_owner}/{self.delivery_repo}"
        self.log.info(f"Cloning {delivery_full}")

        clone_url = self._build_clone_url()
        _git(["clone", "--depth=1", clone_url, self.clone_dir])
        self._configure_git()

        if self.github_api.branch_exists(delivery_full, self.branch):
            raise Exception(f"Results branch {self.branch} already exists on remote")

        _git(["-C", self.clone_dir, "checkout", "-b", self.branch])

    def _build_clone_url(self) -> str:
        """Build HTTPS clone URL with token."""
        return (
            f"https://{self.config.token}@github.com/"
            f"{self.delivery_owner}/{self.delivery_repo}.git"
        )

    def _configure_git(self) -> None:
        """Configure git user and fetch."""
        _git(["-C", self.clone_dir, "config", "user.name", "phems-bot"])
        _git(["-C", self.clone_dir, "config", "user.email", "phems-federated-node@users.noreply.github.com"])
        _git(["-C", self.clone_dir, "fetch", "origin"])

    def _handle_backend(self) -> None:
        """Dispatch based on backend type (git, s3, azure, gcp)."""
        backend_type = self.project.results_backend.type

        if backend_type == "git":
            self.log.info("Backend: git (files committed directly)")
            self.backend_metadata = {"backend": "git"}
        else:
            # s3, azure, gcp all use DVC
            self.log.info(f"Backend: {backend_type} (via DVC)")
            self._init_dvc()
            self._write_dvc_config()
            self._dvc_add_and_push()
            self.backend_metadata = {
                "backend": backend_type,
                "remote_url": self.project.results_backend.config.get("url", "unknown"),
            }

        self._commit_to_git()

    def _init_dvc(self) -> None:
        """Initialize DVC in artifact directory."""
        os.chdir(self.artifact_path)
        _run_cmd(["dvc", "init", "--no-scm"])

    def _write_dvc_config(self) -> None:
        """Write .dvc/config from project config."""
        dvc_dir = self.artifact_path / ".dvc"
        dvc_dir.mkdir(exist_ok=True)

        lines = ['["remote \\"myremote\\""]']
        for key, value in self.project.results_backend.config.items():
            lines.append(f"    {key} = {value}")

        (dvc_dir / "config").write_text("\n".join(lines))
        self.log.info("DVC config written")

    def _dvc_add_and_push(self) -> None:
        """Add results to DVC and push to backend."""
        self.log.info("Adding and pushing to DVC backend")
        _run_cmd(["dvc", "add", "."])
        _run_cmd(["dvc", "push"])

    def _commit_to_git(self) -> None:
        """Stage backend files, write metadata, commit and push."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._stage_backend_files()
        self._write_metadata()
        self._git_commit_and_push()

    def _stage_backend_files(self) -> None:
        """Copy backend-specific files to output directory."""
        # Git backend: copy raw files
        if self.project.results_backend.type == "git":
            for file in self.artifact_path.iterdir():
                if file.is_file():
                    shutil.copy(file, self.output_dir / file.name)

        # DVC backends: copy .dvc files
        else:
            for dvc_file in self.artifact_path.glob("**/*.dvc"):
                rel_path = dvc_file.relative_to(self.artifact_path)
                dest = self.output_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(dvc_file, dest)

    def _write_metadata(self) -> None:
        """Write metadata.json to output directory."""
        metadata = {
            "timestamp": dt.utcnow().isoformat(),
            "id": self.parent_run_id,
            **self.backend_metadata,
        }

        # Include spec from PR or API request
        if self.spec:
            metadata["spec"] = self.spec

        with open(self.output_dir / "metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)

    def _git_commit_and_push(self) -> None:
        """Commit and push results to git."""
        _git(["-C", self.clone_dir, "add", "."])
        _git(["-C", self.clone_dir, "commit", "-m", f"Results: {self.run_dir_name}"])
        _git(["-C", self.clone_dir, "push", "origin", "main"])
        self.log.info(f"Committed and pushed: {self.run_dir_name}")

    def _create_results_pr(self) -> str:
        """Create pull request in delivery repo for results."""
        delivery_full = f"{self.delivery_owner}/{self.delivery_repo}"
        title = f"Results for {self.trigger_owner}/{self.trigger_repo}: {self.run_dir_name}"
        body = (
            f"Automated results for {self.trigger_owner}/{self.trigger_repo}\n"
            f"Directory: {self.run_dir_name}"
        )
        pr_url = self.github_api.create_pull_request(
            delivery_full,
            self.branch,
            self.config.base_branch,
            title,
            body,
        )
        self.log.info(f"Pull request created: {pr_url}")
        return pr_url

    def _cleanup(self) -> None:
        """Clean up temporary directories."""
        shutil.rmtree(self.clone_dir, ignore_errors=True)


def _git(args: list[str], cwd: str | None = None) -> None:
    """Execute a git command."""
    subprocess.run(["git"] + args, cwd=cwd, check=True, capture_output=True, text=True)


def _run_cmd(args: list[str], cwd: str | None = None) -> str:
    """Execute a shell command and return stdout."""
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout
