"""
The REST API of a git provider as the node uses it: the pull requests of a repository, the files in them, and the
branches and commits that make them. One class per provider (`GitHubClient`, `GiteaClient`) over this base, so the
sensors, the results delivery and fncli handle either the same way (ADR 0010).
"""

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime as dt

import requests

from fednode.http import HttpClient

logger = logging.getLogger(__name__)

MERGE_ATTEMPTS = 10
MERGE_RETRY_SECONDS = 3


def parse_time(value: str) -> dt:
    return dt.fromisoformat(value.replace("Z", "+00:00"))


class GitProvider(HttpClient, ABC):
    """
    A git provider's API, authenticated with one token. A repository is named by its path on the provider (owner/name).
    A provider is what its subclass says about paging and about branches, files and merges; the rest is shared.
    """

    # What the provider is called in the log
    name: str
    # The query parameters that list the pull requests most recently updated first
    pulls_order: dict[str, str]

    @abstractmethod
    def page_params(self, page: int) -> dict:
        """The query parameters that ask for one page of a list."""

    @abstractmethod
    def is_last_page(self, items: list[dict]) -> bool:
        """Whether this page of pull requests is the last one."""

    @abstractmethod
    def create_branch(self, repo_path: str, new_branch: str, old_branch: str) -> None:
        """Create new_branch from the head of old_branch."""

    @abstractmethod
    def create_file(self, repo_path: str, file_path: str, content: str, message: str, branch: str):
        """Commit a NEW file to branch. Fails if the file exists: modifying is not supported."""

    @abstractmethod
    def get_file_contents(self, repo_path: str, file_path: str, ref: str) -> str:
        """The contents of a file at a given ref."""

    @abstractmethod
    def _merge(self, repo_path: str, pr_number: int) -> None:
        """Ask for the pull request to be merged with a merge commit."""

    def get_pull_request(self, repo_path: str, pr_number: int) -> dict:
        """Fetch full PR details for a given PR number."""
        logger.info(f"Fetching PR details for {repo_path} PR #{pr_number}")
        return self.request("GET", f"repos/{repo_path}/pulls/{pr_number}").json()

    def get_pulls(self, repo_path: str, since: str, state: str = "all", merged_only: bool = False) -> list[dict]:
        """
        Fetch the PRs in state (open, closed or all) updated after since, into any base branch (the backend matches
        each assignment's), or with merged_only just those merged after since. Lists PRs most recently updated
        first and filters, rather than searching: GitHub's search API allows 30 requests a minute and its index
        lags, which could let the cursor pass a PR before it is found, and Gitea has no search API.
        """
        logger.info(f"Fetching {state} PRs for {repo_path}, updated after {since}")

        since_dt = parse_time(since)
        page = 1
        results = []
        while True:
            items = self.request(
                "GET", f"repos/{repo_path}/pulls",
                params={"state": state, **self.pulls_order, **self.page_params(page)},
            ).json()
            logger.info(f"Fetched {len(items)} {state} PRs from {self.name} for repository {repo_path} (page {page})")

            for item in items:
                # updated_at is never before merged_at, so nothing older can be newly merged
                if parse_time(item["updated_at"]) <= since_dt:
                    return results
                if not merged_only or (item["merged_at"] and parse_time(item["merged_at"]) > since_dt):
                    results.append(item)

            if self.is_last_page(items):
                return results
            page += 1

    def get_pull_request_files(self, repo_path: str, pr_number: int) -> list[dict]:
        """Fetch the files changed in a PR, page by page until an empty one."""
        logger.info(f"Fetching pull request files for {repo_path} PR #{pr_number}")

        page = 1
        files = []
        while True:
            items = self.request(
                "GET", f"repos/{repo_path}/pulls/{pr_number}/files", params=self.page_params(page)
            ).json()
            logger.info(f"Fetched {len(items)} files from {self.name} for PR #{pr_number} (page {page})")
            if not items:
                return files
            files.extend(items)
            page += 1

    def get_default_branch(self, repo_path: str) -> str:
        """The repository's default branch, the one results pull requests go into."""
        return self.request("GET", f"repos/{repo_path}").json()["default_branch"]

    def create_pull_request(
        self, repo_path: str, head_branch: str, base_branch: str, title: str, body: str
    ) -> dict:
        """Create a pull request from head_branch into base_branch."""
        logger.info(f"Creating PR {head_branch} -> {base_branch} in {repo_path}")
        return self.request(
            "POST",
            f"repos/{repo_path}/pulls",
            json={"title": title, "body": body, "head": head_branch, "base": base_branch},
        ).json()

    def merge_pull_request(self, repo_path: str, pr_number: int) -> None:
        """Merge the pull request with a merge commit. Retries on 405 (mergeability computing)."""
        logger.info(f"Merging PR #{pr_number} in {repo_path}")
        for attempt in range(1, MERGE_ATTEMPTS + 1):
            try:
                self._merge(repo_path, pr_number)
                return
            except requests.HTTPError as e:
                if e.response.status_code != 405 or attempt == MERGE_ATTEMPTS:
                    raise
                logger.info(f"Merge returned 405, retrying (attempt {attempt}/{MERGE_ATTEMPTS})")
                time.sleep(MERGE_RETRY_SECONDS)
