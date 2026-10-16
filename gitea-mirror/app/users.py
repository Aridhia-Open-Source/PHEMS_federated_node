from app.clients import GiteaClient, GithubClient
from app.models.mirror import Mirror


def sync_users(mirror: Mirror, github: GithubClient, gitea: GiteaClient) -> dict:
    logins = sorted(set(github.list_users(
        mirror.upstream_uri, mirror.secret_namespace, mirror.secret_key
    )))
    created = [login for login in logins if gitea.ensure_user(login)]
    return {'users': len(logins), 'created': len(created), 'existing': len(logins) - len(created)}
