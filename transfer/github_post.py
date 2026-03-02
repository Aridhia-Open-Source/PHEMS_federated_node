#!/usr/bin/env python3

import os
import subprocess
from datetime import datetime as dt
from datetime import timezone as tz

import requests
from dotenv import load_dotenv

load_dotenv('.dev.env')

GH_TOKEN = os.environ["GH_TOKEN"]
GH_OWNER = os.environ['GH_OWNER']
GH_REPO = os.environ['GH_REPO']
GH_BASE_BRANCH = os.environ['GH_BASE_BRANCH']
GH_WATCH_DIR = os.environ['GH_WATCH_DIR']
GH_MERGED_CURSOR_FILE = os.environ['GH_MERGED_CURSOR_FILE']
MNT_BASE_PATH = os.environ['MNT_BASE_PATH']


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


# def zip_and_upload_results(run_id: str):
#     artifact_path = f"{MNT_BASE_PATH}/{run_id}"
#     if not os.path.exists(artifact_path):
#         raise RuntimeError(f"Artifact path does not exist: {artifact_path}")

#     os.makedirs("/tmp/archives", exist_ok=True)

#     shutil.make_archive(
#         base_name=f"/tmp/archives/{run_id}",
#         root_dir=artifact_path,
#         format='zip',
#     )

#     return f"{MNT_BASE_PATH}/{run_id}.zip"


def upload_github_results_job(run_id: str):
    os.environ['ARTIFACT_PATH'] = f"{MNT_BASE_PATH}/{run_id}"
    subprocess.run(["./scripts/github_push.sh", run_id], check=True)


def dagster_github_results_sensor(run_id, update_cursor: bool = False):
    upload_github_results_job(run_id)


if __name__ == "__main__":
    dagster_github_results_sensor(run_id='request_001', update_cursor=False)
