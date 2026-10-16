"""
Commands for the gitea-mirror service (ADR 0020): add and inspect mirrors of GitHub
repositories, and the webhooks that announce mirrored pull requests. Needs the service
reachable on MIRROR_URL (port-forward it) and its API token in MIRROR_API_TOKEN.
"""

import json

import click
from pydantic import Field

from fncli.cmds.common import to_host_url
from fncli.dagster.config import EnvConfig
from fncli.dagster.mirror import MirrorAPI


class MirrorConfig(EnvConfig):
    mirror_url: str = Field(default="http://localhost:5050", alias="MIRROR_URL")
    mirror_token: str = Field(alias="MIRROR_API_TOKEN")


def build_mirror_api() -> MirrorAPI:
    config = MirrorConfig()
    return MirrorAPI(to_host_url(config.mirror_url), token=config.mirror_token)


def show(data) -> None:
    click.echo(json.dumps(data, indent=2))


@click.group("mirror")
def mirror_group():
    """Manage the gitea-mirror service: mirrors and webhooks."""


@mirror_group.command("add")
@click.option("--upstream-uri", required=True, help="The GitHub repository, an https URL.")
@click.option("--secret-namespace", required=True, help="Namespace of the secret holding the GitHub token.")
@click.option("--secret-key", required=True, help="Name of that secret (its `token` field is the token).")
@click.option("--gitea-owner", required=True, help="Gitea org or user that gets the repository.")
@click.option("--gitea-repo", required=True, help="Gitea repository name.")
@click.option("--base-branch", required=True, help="Branch whose merged pull requests are mirrored.")
@click.option("--disabled", is_flag=True, help="Create the mirror disabled.")
def add_command(upstream_uri, secret_namespace, secret_key, gitea_owner, gitea_repo, base_branch, disabled):
    """Creates a mirror. Its cursor starts now; the response shows the shadow-user preload."""
    body = {
        "upstream_uri": upstream_uri,
        "secret_namespace": secret_namespace,
        "secret_key": secret_key,
        "gitea_owner": gitea_owner,
        "gitea_repo": gitea_repo,
        "base_branch": base_branch,
        "enabled": not disabled,
    }
    show(build_mirror_api().create_mirror(body))


@mirror_group.command("list")
def list_command():
    """Lists the mirrors."""
    show(build_mirror_api().list_mirrors())


@mirror_group.command("status")
@click.argument("mirror_id", type=int)
def status_command(mirror_id):
    """Cursor, last sync, last error, PRs mirrored and whether the GitHub token expired."""
    show(build_mirror_api().get_status(mirror_id))


@mirror_group.command("resync")
@click.argument("mirror_id", type=int)
def resync_command(mirror_id):
    """Runs a sync for the mirror now."""
    show(build_mirror_api().resync(mirror_id))


@mirror_group.command("users-sync")
@click.argument("mirror_id", type=int)
def users_sync_command(mirror_id):
    """Creates shadow Gitea users for the upstream contributors and collaborators."""
    show(build_mirror_api().sync_users(mirror_id))


@mirror_group.group("webhook")
def webhook_group():
    """Subscriptions that receive a signed event for each mirrored pull request."""


@webhook_group.command("add")
@click.option("--url", required=True, help="The endpoint to POST events to (http or https).")
@click.option("--secret-namespace", required=True, help="Namespace of the secret holding the HMAC key.")
@click.option("--secret-key", required=True, help="Name of that secret (its `token` field is the key).")
@click.option("--mirror-id", type=int, default=None, help="Only this mirror's events. Default: all mirrors.")
@click.option("--disabled", is_flag=True, help="Create the webhook disabled.")
def webhook_add_command(url, secret_namespace, secret_key, mirror_id, disabled):
    """Registers a webhook."""
    body = {
        "url": url,
        "secret_namespace": secret_namespace,
        "secret_key": secret_key,
        "mirror_id": mirror_id,
        "enabled": not disabled,
    }
    show(build_mirror_api().create_webhook(body))


@webhook_group.command("list")
def webhook_list_command():
    """Lists the webhooks."""
    show(build_mirror_api().list_webhooks())


@webhook_group.command("deliveries")
@click.argument("webhook_id", type=int)
@click.option("--status", type=click.Choice(["pending", "delivered", "failed"]), default=None)
def webhook_deliveries_command(webhook_id, status):
    """The webhook's latest 100 deliveries, newest first."""
    show(build_mirror_api().list_deliveries(webhook_id, status))


COMMANDS = [mirror_group]
