#!/usr/bin/env python3

import os
from datetime import datetime as dt
from datetime import timezone as tz

import requests
from dotenv import load_dotenv

load_dotenv('.dev.env')

GH_TOKEN = os.environ["GITHUB_TOKEN"]
GH_OWNER = "Aridhia-Open-Source"
GH_REPO = "phems-sandbox"
GH_BASE_BRANCH = "main"
GH_MERGED_CURSOR_FILE = ".github.merged.cursor"


def utc_now():
    return dt.now(tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GithubClient:
    def __init__(self, owner, repo, token, base_branch):
        self.owner = owner
        self.repo = repo
        self.token = token
        self.base_branch = base_branch

    @property
    def repo_uri(self):
        return f"https://api.github.com/repos/{self.owner}/{self.repo}"

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
        }

    def get_pull_requests(self, cursor: str | None = None, per_page: int = 100):
        params = {
            "state": "closed",
            "base": self.base_branch,
            "per_page": per_page,
            "sort": "updated",
            "direction": "desc",
        }

        page = 1
        results = []

        while True:
            params["page"] = page
            response = self.request("GET", "/pulls", params=params)
            prs = response.json()

            if not prs:
                break

            for pr in prs:
                merged_at = pr.get("merged_at")
                if not merged_at:
                    continue

                if cursor and merged_at <= cursor:
                    continue

                results.append(pr)

            page += 1

        return results

    def request(self, verb, path=None, params=None, headers=None, raise_for_status=True):
        params = params or {}

        if path and path.startswith("/search/"):
            uri = f"https://api.github.com{path}"
        else:
            uri = f"{self.repo_uri}/{(path or '').lstrip('/')}"

        headers = {**self.headers, **(headers or {})}
        response = requests.request(verb, uri, headers=headers, params=params)
        if raise_for_status:
            response.raise_for_status()
        return response


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


if __name__ == "__main__":
    client = GithubClient(
        owner=GH_OWNER,
        repo=GH_REPO,
        token=GH_TOKEN,
        base_branch=GH_BASE_BRANCH,
    )

    cursor = FileCursor(GH_MERGED_CURSOR_FILE)

    pullreqs = client.get_pull_requests(cursor=cursor.value, per_page=3)

    for pr in pullreqs:
        print(pr["number"], pr["merged_at"])

    if pullreqs:
        newest = max(pr["merged_at"] for pr in pullreqs)
        cursor.value = newest
