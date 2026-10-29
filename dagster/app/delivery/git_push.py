"""Provider-neutral git and zip helpers for pushing files to a repository."""

import base64
import logging
import os
import subprocess
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

COMMITTER_NAME = "phems-bot"
COMMITTER_EMAIL = "phems-federated-node@users.noreply.github.com"
# Per git command: delivery clones the results repository and pushes up to 10MB zipped
GIT_TIMEOUT_SECONDS = 60


def clone_url(provider_uri: str, repo_path: str) -> str:
    """The URL to clone a repository from: the provider's uri, the repo_path and '.git'."""
    return f"{provider_uri}/{repo_path}.git"


def auth_env(token: str) -> dict[str, str]:
    """
    Environment that makes git send the token as basic auth to every remote it talks to.
    Kept out of the command line and the remote URL so it cannot leak through an error.
    """
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
        "GIT_TERMINAL_PROMPT": "0",
    }


def git(args: list[str], cwd: str | Path | None = None, env: dict[str, str] | None = None) -> str:
    """Run a git command and return its stdout. A failure or a timeout raises."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"git {args[0]} timed out after {GIT_TIMEOUT_SECONDS}s") from e
    if result.returncode:
        raise RuntimeError(f"git {args[0]} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def zip_dir(src: Path, dest_zip: Path) -> int:
    """
    Zip a directory into a file and return how many files went in. A symbolic link is left out, not
    followed: it may point out of the directory. So is a file whose name has a backslash, which Windows
    unzip tools read as a path.
    """
    file_count = 0
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(src.rglob("*")):
            if file.is_file() and not file.is_symlink():
                name = file.relative_to(src)
                if "\\" in str(name):
                    logger.warning(f"Left {name} out of the results: its name has a backslash")
                    continue
                zf.write(file, name)
                file_count += 1
    return file_count


def clone(url: str, dest: Path, env: dict[str, str]) -> None:
    """Shallow-clone the default branch and set the committer."""
    git(["clone", "--depth=1", url, str(dest)], env=env)
    git(["config", "user.name", COMMITTER_NAME], cwd=dest)
    git(["config", "user.email", COMMITTER_EMAIL], cwd=dest)


def current_branch(repo_dir: Path) -> str:
    """The checked-out branch: right after a clone, the remote's default branch."""
    return git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir)


def remote_branch_sha(repo_dir: Path, branch: str, env: dict[str, str]) -> str | None:
    """The sha the branch points at on the remote, or None if the remote has no such branch."""
    out = git(["ls-remote", "--heads", "origin", f"refs/heads/{branch}"], cwd=repo_dir, env=env)
    return out.split()[0] if out else None


def checkout_new_branch(repo_dir: Path, branch: str) -> None:
    """Start a new branch from the cloned commit."""
    git(["checkout", "-b", branch], cwd=repo_dir)


def commit_and_push(repo_dir: Path, message: str, env: dict[str, str]) -> str:
    """Commit everything, push it to the current branch, and return the commit sha."""
    git(["add", "."], cwd=repo_dir)
    git(["commit", "-m", message], cwd=repo_dir)
    git(["push", "origin", "HEAD"], cwd=repo_dir, env=env)
    return git(["rev-parse", "HEAD"], cwd=repo_dir)
