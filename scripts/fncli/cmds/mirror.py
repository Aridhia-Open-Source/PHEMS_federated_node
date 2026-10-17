"""
Commands for the gitea-mirror service (ADR 0020): add and inspect mirrors of GitHub
repositories, and the webhooks that announce mirrored pull requests. Needs the service
reachable on MIRROR_URL (port-forward it) and its API token in MIRROR_API_TOKEN.
"""

import functools
import json

import click
import requests
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


def service_error(err: requests.HTTPError) -> str:
    """The service's JSON `error` (400, 409, 502 ...) with the status, else the HTTP error text."""
    response = err.response
    if response is None:
        return str(err)
    try:
        detail = response.json().get("error")
    except (ValueError, AttributeError):
        detail = None
    return f"HTTP {response.status_code}: {detail or err}"


def mirror_command(group, name):
    """Registers a command whose HTTP errors are shown as the service's message, not a traceback."""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except requests.HTTPError as err:
                raise click.ClickException(service_error(err)) from None
        return group.command(name)(wrapper)
    return decorator


@click.group("mirror")
def mirror_group():
    """Manage the gitea-mirror service: mirrors and webhooks."""


@mirror_command(mirror_group, "add")
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


@mirror_command(mirror_group, "list")
def list_command():
    """Lists the mirrors."""
    show(build_mirror_api().list_mirrors())


@mirror_command(mirror_group, "status")
@click.argument("mirror_id", type=int)
def status_command(mirror_id):
    """Cursor, last sync, last error, PRs mirrored and whether the GitHub token expired."""
    show(build_mirror_api().get_status(mirror_id))


@mirror_command(mirror_group, "delete")
@click.argument("mirror_id", type=int)
def delete_command(mirror_id):
    """Deletes a mirror (its state, pull request rows and the webhooks scoped to it go too; the Gitea repository stays)."""
    build_mirror_api().delete_mirror(mirror_id)
    show({"deleted": mirror_id})


@mirror_command(mirror_group, "disable")
@click.argument("mirror_id", type=int)
def disable_command(mirror_id):
    """Stops syncing the mirror (PATCH enabled=false)."""
    show(build_mirror_api().set_mirror_enabled(mirror_id, False))


@mirror_command(mirror_group, "enable")
@click.argument("mirror_id", type=int)
def enable_command(mirror_id):
    """Resumes syncing the mirror (PATCH enabled=true)."""
    show(build_mirror_api().set_mirror_enabled(mirror_id, True))


@mirror_command(mirror_group, "resync")
@click.argument("mirror_id", type=int)
def resync_command(mirror_id):
    """Runs a sync for the mirror now."""
    show(build_mirror_api().resync(mirror_id))


@mirror_command(mirror_group, "users-sync")
@click.argument("mirror_id", type=int)
def users_sync_command(mirror_id):
    """Creates shadow Gitea users for the upstream contributors and collaborators."""
    show(build_mirror_api().sync_users(mirror_id))


@mirror_group.group("webhook")
def webhook_group():
    """Subscriptions that receive a signed event for each mirrored pull request."""


@mirror_command(webhook_group, "add")
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


@mirror_command(webhook_group, "list")
def webhook_list_command():
    """Lists the webhooks."""
    show(build_mirror_api().list_webhooks())


@mirror_command(webhook_group, "deliveries")
@click.argument("webhook_id", type=int)
@click.option("--status", type=click.Choice(["pending", "delivered", "failed"]), default=None)
def webhook_deliveries_command(webhook_id, status):
    """The webhook's latest 100 deliveries, newest first."""
    show(build_mirror_api().list_deliveries(webhook_id, status))


@mirror_command(webhook_group, "delete")
@click.argument("webhook_id", type=int)
def webhook_delete_command(webhook_id):
    """Deletes a webhook."""
    build_mirror_api().delete_webhook(webhook_id)
    show({"deleted": webhook_id})


@mirror_command(webhook_group, "disable")
@click.argument("webhook_id", type=int)
def webhook_disable_command(webhook_id):
    """Stops sending events to the webhook (PATCH enabled=false)."""
    show(build_mirror_api().set_webhook_enabled(webhook_id, False))


@mirror_command(webhook_group, "enable")
@click.argument("webhook_id", type=int)
def webhook_enable_command(webhook_id):
    """Resumes sending events to the webhook (PATCH enabled=true)."""
    show(build_mirror_api().set_webhook_enabled(webhook_id, True))


COMMANDS = [mirror_group]
