"""
`fncli gitea setup -f FILE` makes what the Gitea Repository resources of node config files (config/, ADR 0032) need
before kubectl applies them: each repository in Gitea, under the node's Gitea admin user, and for each NodeSecret they
name, a Gitea OAuth app of the NodeSecret's name, authorized, with its credentials (CLIENT_ID, CLIENT_SECRET,
REFRESH_TOKEN) in the Kubernetes Secret the NodeSecret reads (fromSecret, in its namespace). A Secret that exists is
kept: authorizing again replaces the app's client secret, so only --rotate does. A repository is a Gitea one when its
host is a gitea GitProvider's, in the files or on the cluster. Dev only: production Secrets come from SOPS or External
Secrets.
"""

from pathlib import Path

import click

from nexus_client.git_uri import normalise_provider_uri, normalise_repo_uri
from fncli.cmds.common import GiteaConfig, build_gitea_api
from fncli.cmds.target import check_kube_context, context_option, quiet_backend_logs
from fncli.context import Context
from fncli.k8s import k8s_secret_version, list_node_config, write_k8s_secret
from fncli.node_config import load_resources, of_kind


def gitea_providers(resources: list[dict]) -> dict[str, str]:
    """host[:port] -> uri of every gitea GitProvider in the files and on the cluster"""
    providers = of_kind(resources, "GitProvider") + list_node_config("gitproviders")
    return {
        normalise_provider_uri(p["spec"]["uri"]).split("://")[1]: p["spec"]["uri"]
        for p in providers if p["spec"]["type"] == "gitea"
    }


def gitea_repositories(resources: list[dict], providers: dict[str, str], admin_user: str) -> list[dict]:
    """The files' Repository resources on a Gitea, which must be the admin user's: the only one fncli can create"""
    repositories = [r for r in of_kind(resources, "Repository") if normalise_repo_uri(r["spec"]["uri"]).split("/")[0] in providers]
    wrong = [r["spec"]["uri"] for r in repositories if normalise_repo_uri(r["spec"]["uri"]).split("/")[1] != admin_user.lower()]
    if wrong:
        raise click.ClickException(f"Not owned by the Gitea admin user {admin_user}: {', '.join(wrong)}")
    return repositories


def node_secrets(resources: list[dict], repositories: list[dict]) -> dict[str, dict]:
    """The NodeSecrets the repositories name, by name: each must be in the files and read one Secret (fromSecret)"""
    in_files = {secret["metadata"]["name"]: secret for secret in of_kind(resources, "NodeSecret")}
    names = sorted({repository["spec"]["secret"] for repository in repositories})
    problems = [name for name in names if "fromSecret" not in in_files.get(name, {}).get("spec", {})]
    if problems:
        raise click.ClickException(f"Not a NodeSecret with fromSecret in the files: {', '.join(problems)}")
    return {name: in_files[name] for name in names}


def gitea_setup(context: Context, paths: list[Path], rotate: tuple[str, ...]):
    check_kube_context(context)
    resources = load_resources(paths)
    providers = gitea_providers(resources)
    repositories = gitea_repositories(resources, providers, context.node.gitea_admin_user)
    secrets = node_secrets(resources, repositories)
    unknown = [label for label in rotate if label not in secrets]
    if unknown:
        raise click.ClickException(f"--rotate: {', '.join(unknown)} is not a NodeSecret of a Gitea repository in the files")
    if not repositories:
        click.echo("No Gitea repositories in the files.")
        return
    host = normalise_repo_uri(repositories[0]["spec"]["uri"]).split("/")[0]
    gitea = build_gitea_api(GiteaConfig(node=context.node, gitea_url=providers[host]))
    with quiet_backend_logs():
        for repository in repositories:
            name = normalise_repo_uri(repository["spec"]["uri"]).split("/")[2]
            gitea.get_or_create_repo(name)
            click.echo(f"  repository {name}: in Gitea")
        for label, secret in secrets.items():
            namespace = secret["metadata"]["namespace"]
            secret_name = secret["spec"]["fromSecret"]["name"]
            if k8s_secret_version(secret_name, namespace) is not None and label not in rotate:
                click.echo(f"  secret {namespace}/{secret_name}: kept (--rotate {label} replaces it)")
                continue
            tokens = gitea.authorize_oauth_app(label)
            write_k8s_secret(secret_name, namespace, {
                "CLIENT_ID": tokens["client_id"],
                "CLIENT_SECRET": tokens["client_secret"],
                "REFRESH_TOKEN": tokens["refresh_token"],
            })
            click.echo(f"  secret {namespace}/{secret_name}: written from Gitea OAuth app {label}")


@click.group("gitea")
def gitea_group():
    """The dev cluster's Gitea, for the node config in config/."""


@gitea_group.command("setup")
@click.option(
    "-f", "--file", "paths", multiple=True, required=True, type=click.Path(exists=True, path_type=Path),
    help="A node config file, or a directory of them (its *.yaml), as kubectl -f takes it. Repeatable.",
)
@context_option
@click.option(
    "--rotate", multiple=True, metavar="NODESECRET",
    help="Authorize this NodeSecret's OAuth app again and rewrite its Secret, though it exists (repeatable). The "
    "operator sends the new values to nexus-api on its next sync.",
)
def setup_command(paths, context, rotate):
    """
    Make the Gitea repositories of the files' Repository resources, and the Kubernetes Secrets of the NodeSecrets
    they name, from Gitea OAuth apps of the NodeSecrets' names. Run it before `kubectl apply -f` of the same files.
    Safe to rerun: a Secret that exists is kept unless --rotate names it.
    """
    gitea_setup(context, list(paths), rotate)


COMMANDS = [gitea_group]
