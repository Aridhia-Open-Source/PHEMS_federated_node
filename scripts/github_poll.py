#!/usr/bin/env python3

import os
import base64
import json

from datetime import datetime as dt
from datetime import timezone as tz
from datetime import timedelta as td


import requests
from dotenv import load_dotenv

load_dotenv('.dev.env')

GH_API_BASE_URI = "https://api.github.com"
GH_TOKEN = os.environ["GH_TOKEN"]
GH_OWNER = os.environ['GH_OWNER']
GH_REPO = os.environ['GH_REPO']
GH_BASE_BRANCH = os.environ['GH_BASE_BRANCH']
GH_WATCH_DIR = os.environ['GH_WATCH_DIR']
GH_MERGED_CURSOR_FILE = os.environ['GH_MERGED_CURSOR_FILE']
MNT_BASE_PATH = os.environ['MNT_BASE_PATH']


def utc_now():
    return (dt.now(tz.utc) - td(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")


class FileCursor:
    def __init__(self, path: str, init_to_now: bool = True):
        self.path = path

        if not os.path.exists(self.path):
            if not init_to_now:
                raise RuntimeError(f"Cursor file missing: {self.path}")
            self.value = utc_now()

    def __str__(self):
        return self.value

    @property
    def value(self) -> str:
        if not os.path.exists(self.path):
            raise RuntimeError(f"Cursor file missing: {self.path}")
        with open(self.path, "r") as f:
            ts = f.read().strip()
        if not ts:
            raise RuntimeError(f"Cursor file empty: {self.path}")
        return ts

    @value.setter
    def value(self, ts: str):
        with open(self.path, "w") as f:
            f.write(str(ts))


class GithubClient:
    def __init__(self, owner, repo, token, base_branch):
        self.owner = owner
        self.repo = repo
        self.token = token
        self.base_branch = base_branch

    @property
    def repo_uri(self):
        return f"{GH_API_BASE_URI}/repos/{self.owner}/{self.repo}"

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
        }

    def get_new_merged_pulls(self, cursor: str, watch_dir: str, per_page: int = 100):
        page = 1
        results = []

        while True:
            query = (
                f"repo:{self.owner}/{self.repo} "
                f"is:pr "
                f"is:merged "
                f"base:{self.base_branch} "
                f"merged:>{cursor}"
            )

            params = {
                "q": query,
                "per_page": per_page,
                "page": page,
            }

            response = self.request("GET", "/search/issues", params=params)
            data = response.json()
            items = data.get("items")
            if not items:
                return results

            print(f"Processing PRs merged after {cursor} (page {page})...")
            for item in items:
                pr_number = item["number"]
                pr = self.request("GET", f"/pulls/{pr_number}").json()
                pr_files = self.get_pull_request_file_names(pr_number)
                pr["watched_files"] = self._filter_watched_dir(pr_files, watch_dir)
                if not pr["watched_files"]:
                    continue

                results.append(pr)

            page += 1

    def get_pull_request_file_names(self, pr_number):
        return self.request("GET", f"/pulls/{pr_number}/files").json()

    def get_file_contents(self, path: str, ref: str):
        response = self.request(
            "GET",
            f"/contents/{path}",
            params={"ref": ref},
        )
        data = response.json()

        if data["encoding"] != "base64":
            raise RuntimeError("Unexpected encoding")

        return base64.b64decode(data["content"]).decode("utf-8")

    def request(self, verb, path=None, params=None, headers=None, raise_for_status=True):
        params = params or {}
        uri = self._make_uri(path)
        headers = {**self.headers, **(headers or {})}
        response = requests.request(verb, uri, headers=headers, params=params)
        if raise_for_status:
            response.raise_for_status()
        return response

    def _make_uri(self, path=None):
        path = (path or '').lstrip('/')
        if path.startswith("search"):
            return f"{GH_API_BASE_URI}/{path}"
        return f"{self.repo_uri}/{path}"

    def _filter_watched_dir(self, files, watch_dir: str):
        return [
            f['filename'] for f in files
            if f["filename"].startswith(watch_dir)
            and f["status"] == "added"
            and f["filename"].endswith(".json")
        ]


def dagster_github_polling_sensor(update_cursor=True):
    client = GithubClient(
        owner=GH_OWNER,
        repo=GH_REPO,
        token=GH_TOKEN,
        base_branch=GH_BASE_BRANCH,
    )

    cursor = FileCursor(GH_MERGED_CURSOR_FILE)

    pullreqs = client.get_new_merged_pulls(
        cursor=str(cursor),
        watch_dir=GH_WATCH_DIR,
        per_page=100
    )

    for pr in pullreqs:
        print(pr['number'], pr['merged_at'], pr['watched_files'])
        for fp in pr['watched_files']:
            content = client.get_file_contents(fp, ref=pr['merge_commit_sha'])
            data = json.loads(content)
            print(data['spec']['docker_image'])
            # breakpoint()

    if pullreqs and update_cursor:
        newest = max(pr["merged_at"] for pr in pullreqs)
        cursor.value = newest


if __name__ == "__main__":
    dagster_github_polling_sensor(update_cursor=False)
