import base64
import requests as req

GH_API_BASE_URL = "https://api.github.com"


class GithubClient:
    def __init__(self, token: str, session=None):
        self._session = session or req.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        })

    def request(self, method: str, path: str, raise_for_status: bool = True, **kwargs) -> req.Response:
        url = f"{GH_API_BASE_URL}/{path.lstrip('/')}"
        response = self._session.request(method, url, timeout=10, **kwargs)
        if raise_for_status:
            response.raise_for_status()
        return response


class GithubAPI:
    def __init__(self, client: GithubClient):
        self.client = client

    def get_new_merged_pulls(self, repo_uri: str, base_branch: str, cursor: str, watch_dir: str, per_page: int = 100):
        page = 1
        results = []

        while True:
            query = (
                f"repo:{repo_uri} "
                f"is:pr is:merged "
                f"base:{base_branch} "
                f"merged:>{cursor}"
            )
            response = self.client.request(
                "GET", "search/issues",
                params={"q": query, "per_page": per_page, "page": page},
            )
            items = response.json().get("items")
            if not items:
                return results

            for item in items:
                pr_number = item["number"]
                pr = self.client.request("GET", f"repos/{repo_uri}/pulls/{pr_number}").json()
                pr_files = GithubAPI.get_pull_request_files(self, repo_uri, pr_number)
                pr["watched_files"] = self._filter_watched_dir(pr_files, watch_dir)
                if pr["watched_files"]:
                    results.append(pr)

            page += 1

    def get_merged_prs_after_number(self, repo_uri: str, base_branch: str, pr_cursor: int, watch_dir: str, per_page: int = 100):
        page = 1
        results = []

        while True:
            query = (
                f"repo:{repo_uri} "
                f"is:pr is:merged "
                f"base:{base_branch}"
            )
            response = self.client.request(
                "GET", "search/issues",
                params={"q": query, "per_page": per_page, "page": page,
                        "sort": "created", "order": "desc"},
            )
            items = response.json().get("items", [])

            if not items:
                return results

            found_new = False
            for item in items:
                if item["number"] <= pr_cursor:
                    continue
                found_new = True
                pr_number = item["number"]
                pr = self.client.request("GET", f"repos/{repo_uri}/pulls/{pr_number}").json()
                pr_files = GithubAPI.get_pull_request_files(self, repo_uri, pr_number)
                pr["watched_files"] = self._filter_watched_dir(pr_files, watch_dir)
                if pr["watched_files"]:
                    results.append(pr)

            if not found_new:
                return results

            page += 1

    def get_pull_request_files(self, repo_uri: str, pr_number: int):
        page = 1
        files = []
        while True:
            response = self.client.request(
                "GET", f"repos/{repo_uri}/pulls/{pr_number}/files",
                params={"per_page": 100, "page": page},
            )
            page_files = response.json()
            if not page_files:
                break
            files.extend(page_files)
            page += 1
        return files

    def get_file_contents(self, repo_uri: str, path: str, ref: str) -> str:
        response = self.client.request(
            "GET", f"repos/{repo_uri}/contents/{path}",
            params={"ref": ref},
        )
        data = response.json()
        return base64.b64decode(data["content"]).decode("utf-8")

    def add_pull_request_comment(self, repo_uri: str, pr_number: int, body: str):
        response = self.client.request(
            "POST", f"repos/{repo_uri}/issues/{pr_number}/comments",
            json={"body": body},
        )
        return response.json()

    @staticmethod
    def _filter_watched_dir(files, watch_dir: str):
        return [
            f["filename"] for f in files
            if f["filename"].startswith(watch_dir)
            and f["status"] == "added"
            and f["filename"].endswith(".json")
        ]


class GithubRepo(GithubAPI):
    def __init__(self, client: GithubClient, uri: str, base_branch: str = "main"):
        super().__init__(client)
        self.uri = uri
        self.base_branch = base_branch

    @property
    def _repo_uri(self) -> str:
        # "github.com/org/repo" → "org/repo"
        return self.uri.split("/", 1)[1]

    def get_new_merged_pulls(self, cursor: str, watch_dir: str, per_page: int = 100):
        return super().get_new_merged_pulls(self._repo_uri, self.base_branch, cursor, watch_dir, per_page)

    def get_merged_prs_after_number(self, pr_cursor: int, watch_dir: str, per_page: int = 100):
        return super().get_merged_prs_after_number(self._repo_uri, self.base_branch, pr_cursor, watch_dir, per_page)

    def get_pull_request_files(self, pr_number: int):
        return super().get_pull_request_files(self._repo_uri, pr_number)

    def get_file_contents(self, path: str, ref: str) -> str:
        return super().get_file_contents(self._repo_uri, path, ref)

    def add_pull_request_comment(self, pr_number: int, body: str):
        return super().add_pull_request_comment(self._repo_uri, pr_number, body)
