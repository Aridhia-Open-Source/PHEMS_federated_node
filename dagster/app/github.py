import base64
from datetime import datetime as dt
from datetime import timezone as tz

import requests

GH_API_BASE_URI = "https://api.github.com"


def utc_from(ts: str) -> dt:
    return dt.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=tz.utc)


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
        cursor_dt = utc_from(cursor)

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
                if utc_from(pr["merged_at"]) <= cursor_dt:
                    continue

                pr_files = self.get_pull_request_files(pr_number)
                pr["watched_files"] = self._filter_watched_dir(pr_files, watch_dir)
                if not pr["watched_files"]:
                    continue

                results.append(pr)

            page += 1

    def get_search_issues(self, params):
        return self.request("GET", "/search/issues", params=params).json()

    def get_pull_request_by_head(self, head_branch: str):
        response = self.request(
            "GET",
            "/pulls",
            params={
                "head": f"{self.owner}:{head_branch}",
                "state": "open",
            },
        )
        prs = response.json()
        return prs[0] if prs else None

    def get_pull_request_files(self, pr_number):
        return self.request("GET", f"/pulls/{pr_number}/files").json()

    def get_file_contents(self, path: str, ref: str):
        response = self.request(
            "GET",
            f"/contents/{path}",
            params={"ref": ref},
        )
        data = response.json()
        return base64.b64decode(data["content"]).decode("utf-8")

    def add_pull_request_comment(self, pr_number, body):
        response = self.request(
            "POST",
            f"/issues/{pr_number}/comments",
            json={"body": body},
        )
        return response.json()

    def request(
            self,
            verb,
            path=None,
            params=None,
            headers=None,
            json=None,
            raise_for_status=True
    ):
        params = params or {}
        uri = self._make_uri(path)
        headers = {**self.headers, **(headers or {})}
        response = requests.request(verb, uri, headers=headers, params=params, json=json)
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