import base64
import logging
import time
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

from app.gitea import GITEA_API_BASE_URL
from app.utils import HttpClient

default_logger = logging.getLogger(__name__)

# The redirect_uri of the OAuth2 applications fncli creates. Nothing serves it: the
# authorization code is read from the Location header of the redirect to it.
OAUTH_REDIRECT_URI = "http://localhost/fn-callback"
OAUTH_STATE = "fncli"


class GiteaAdminClient(HttpClient):
    """Admin calls authenticate as the admin user rather than with an access token."""

    def __init__(self, username: str, password: str, session=None, base_uri: str = GITEA_API_BASE_URL):
        super().__init__(base_uri, session=session)
        self._session.auth = (username, password)


class HiddenInputs(HTMLParser):
    """The hidden inputs of a page: how Gitea's forms carry their CSRF token (older versions) and the OAuth2 request."""

    def __init__(self):
        super().__init__()
        self.fields: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input" and attributes.get("type") == "hidden":
            self.fields[attributes["name"]] = attributes.get("value", "")


def hidden_inputs(page: str) -> dict[str, str]:
    parser = HiddenInputs()
    parser.feed(page)
    return parser.fields


class GiteaWebClient(HttpClient):
    """
    Gitea's pages and OAuth2 endpoints, which sit outside /api/v1, driven the way a browser
    would. The session keeps the login cookie.
    """

    def __init__(self, username: str, password: str, session=None, base_uri: str = ""):
        super().__init__(base_uri, session=session)
        self.username = username
        self.password = password

    def login(self):
        """Sign in with the form's fields: Gitea 28 has no CSRF token on it, older versions do (_csrf)."""
        fields = hidden_inputs(self.get("user/login").text)
        response = self.post(
            "user/login",
            data={**fields, "user_name": self.username, "password": self.password},
            allow_redirects=False,
        )
        # A wrong password is a 200 with the form again
        if response.status_code != 303:
            raise RuntimeError(f"Gitea login as {self.username} failed ({response.status_code})")

    def authorize(self, client_id: str, redirect_uri: str) -> str:
        """
        The authorization code. The first time a user authorises an application Gitea asks for
        consent, even with skip_secondary_authorization, so the consent form is posted. Every
        later time it redirects straight away.
        """
        response = self.get(
            "login/oauth/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "state": OAUTH_STATE,
            },
            allow_redirects=False,
        )
        if response.status_code == 200:
            response = self.post(
                "login/oauth/grant",
                data={**hidden_inputs(response.text), "granted": "true"},
                allow_redirects=False,
            )
        query = parse_qs(urlparse(response.headers["Location"]).query)
        if "code" not in query:
            raise RuntimeError(f"Gitea did not authorise the application: {query}")
        return query["code"][0]

    def exchange_code(self, client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict:
        """The access_token (valid for ACCESS_TOKEN_EXPIRATION_TIME), refresh_token and expires_in of an authorization code."""
        response = self.post(
            "login/oauth/access_token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        return response.json()


class GiteaAdminAPI:
    def __init__(self, client: GiteaAdminClient, username: str, web: GiteaWebClient, logger=None):
        self.client = client
        self.username = username
        self.web = web
        self.logger = logger or default_logger

    def get_or_create_repo(self, name: str, description: str = "") -> dict:
        """Fetch the admin user's repo, creating it (with an initial commit) if missing."""
        response = self.client.request(
            "GET", f"repos/{self.username}/{name}", raise_for_status=False
        )
        if response.status_code != 404:
            self.logger.info(f"Repo {name} already exists")
        else:
            self.logger.info(f"Creating repo {name}")
            response = self.client.request(
                "POST",
                "user/repos",
                json={"name": name, "description": description, "private": False, "auto_init": True},
            )
        response.raise_for_status()
        return response.json()

    def delete_repo(self, name: str) -> bool:
        """Delete the admin user's repo. Returns whether there was one to delete."""
        response = self.client.request(
            "DELETE", f"repos/{self.username}/{name}", raise_for_status=False
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def delete_token(self, name: str) -> bool:
        """Delete the admin user's token. Returns whether there was one to delete."""
        response = self.client.request(
            "DELETE", f"users/{self.username}/tokens/{name}", raise_for_status=False
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def replace_token(self, name: str, scopes: list[str]) -> str:
        """
        Gitea only returns a token's value when it is created, so replace any previous
        token under the same name rather than pile up new ones on every run.
        """
        self.delete_token(name)
        response = self.client.request(
            "POST", f"users/{self.username}/tokens", json={"name": name, "scopes": scopes}
        )
        return response.json()["sha1"]

    def find_oauth_app(self, name: str) -> dict | None:
        """The admin user's OAuth2 application of that name, if any."""
        apps = self.client.request("GET", "user/applications/oauth2", params={"limit": 50}).json()
        return next((app for app in apps if app["name"] == name), None)

    def get_or_create_oauth_app(self, name: str, redirect_uri: str) -> dict:
        """
        The admin user's OAuth2 application of that name, with its client_secret. Gitea shows a
        secret only when the application is created or edited, so an existing one is edited
        (nothing changes but the secret, which is new: the old one stops working).
        """
        fields = {
            "name": name,
            "redirect_uris": [redirect_uri],
            "confidential_client": True,
            "skip_secondary_authorization": True,
        }
        app = self.find_oauth_app(name)
        if app:
            self.logger.info(f"OAuth2 application {name} already exists, new secret")
            response = self.client.request("PATCH", f"user/applications/oauth2/{app['id']}", json=fields)
        else:
            self.logger.info(f"Creating OAuth2 application {name}")
            response = self.client.request("POST", "user/applications/oauth2", json=fields)
        return response.json()

    def delete_oauth_app(self, name: str) -> bool:
        """Delete the admin user's OAuth2 application, and with it the tokens it issued. Returns whether there was one to delete."""
        app = self.find_oauth_app(name)
        if app is None:
            return False
        self.client.request("DELETE", f"user/applications/oauth2/{app['id']}")
        return True

    def authorize_oauth_app(self, name: str) -> dict:
        """
        Authorise the admin user's OAuth2 application of that name without a browser (it is created
        if missing) and return its client_id and client_secret with the access_token and
        refresh_token Gitea issued.
        """
        app = self.get_or_create_oauth_app(name, OAUTH_REDIRECT_URI)
        self.web.login()
        code = self.web.authorize(app["client_id"], OAUTH_REDIRECT_URI)
        tokens = self.web.exchange_code(app["client_id"], app["client_secret"], code, OAUTH_REDIRECT_URI)
        return {"client_id": app["client_id"], "client_secret": app["client_secret"], **tokens}

    def create_branch(self, repo_path: str, new_branch: str, old_branch: str) -> None:
        """Create new_branch from the head of old_branch."""
        self.logger.info(f"Creating branch {new_branch} from {old_branch} in {repo_path}")
        self.client.request(
            "POST",
            f"repos/{repo_path}/branches",
            json={"new_branch_name": new_branch, "old_branch_name": old_branch},
        )

    def create_file(self, repo_path: str, file_path: str, content: str, message: str, branch: str):
        """Commit a NEW file to branch. Fails if the file exists: modifying is not supported."""
        self.logger.info(f"Committing {file_path} to {branch} in {repo_path}")
        self.client.request(
            "POST",
            f"repos/{repo_path}/contents/{file_path}",
            json={
                "content": base64.b64encode(content.encode()).decode(),
                "message": message,
                "branch": branch,
            },
        )

    def create_pull_request(
        self, repo_path: str, head_branch: str, base_branch: str, title: str, body: str
    ) -> dict:
        """Create a pull request from head_branch into base_branch."""
        self.logger.info(f"Creating PR {head_branch} -> {base_branch} in {repo_path}")
        response = self.client.request(
            "POST",
            f"repos/{repo_path}/pulls",
            json={"title": title, "body": body, "head": head_branch, "base": base_branch},
        )
        return response.json()

    def merge_pull_request(self, repo_path: str, pr_number: int) -> None:
        """Merge the pull request with a merge commit. Retries on 405 (mergeability computing)."""
        self.logger.info(f"Merging PR #{pr_number} in {repo_path}")
        max_attempts = 10
        for attempt in range(1, max_attempts + 1):
            try:
                self.client.request(
                    "POST", f"repos/{repo_path}/pulls/{pr_number}/merge", json={"Do": "merge"}
                )
                return
            except Exception as e:
                if hasattr(e, 'response') and hasattr(e.response, 'status_code') and e.response.status_code == 405:
                    if attempt < max_attempts:
                        self.logger.info(f"Merge returned 405, retrying (attempt {attempt}/{max_attempts})")
                        time.sleep(3)
                    else:
                        self.logger.error(f"Merge failed with 405 after {max_attempts} attempts")
                        raise
                else:
                    raise
