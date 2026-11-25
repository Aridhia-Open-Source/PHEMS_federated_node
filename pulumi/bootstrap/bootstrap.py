"""Pulumi resources for a site's GitHub deployment repository.

The repository is deliberately the boundary between infrastructure and Flux:
Pulumi creates the repository and its initial declarative files, while Flux
reads and applies the committed files in the site's cluster.
"""

from pathlib import Path

import pulumi
import pulumi_github as github


ROOT = Path(__file__).parent
FILES = (
    "README.md",
    "kustomization.yaml",
    "namespaces.yaml",
    "helmrepository.yaml",
    "helmrelease.yaml",
    "values.yaml",
    "kustomizeconfig.yaml",
)


def _render(
    path: str,
    *,
    site: str,
    namespace: str,
    chart_version: str,
    release_name: str,
) -> str:
    content = (ROOT / "files" / path).read_text(encoding="utf-8")
    return (
        content.replace("{{SITE}}", site)
        .replace("{{NAMESPACE}}", namespace)
        .replace("{{CHART_VERSION}}", chart_version)
        .replace("{{RELEASE_NAME}}", release_name)
    )


def create_deployment_repository() -> github.Repository:
    """Create the deployment repository and converge its initial files."""

    config = pulumi.Config()
    owner = config.require("github:owner")
    repository_name = config.get("repository") or "phems-deployment"
    site = config.get("site") or "site"
    namespace = config.get("namespace") or "fn"
    chart_version = config.get("chart-version") or "0.0.1"
    release_name = config.get("release-name") or "federated-node"
    default_branch = "main"

    provider = github.Provider("github", owner=owner)
    repository = github.Repository(
        "deployment-repository",
        name=repository_name,
        description=f"PHEMS deployment configuration for {site}",
        private=True,
        auto_init=True,
        has_issues=False,
        has_projects=False,
        has_wiki=False,
        delete_branch_on_merge=True,
        provider=provider,
    )

    # auto_init gives both a new repository and an imported empty repository a
    # commit on main. RepositoryFile is then safe to retry and overwrites only
    # the files owned by this stack.
    for path in FILES:
        github.RepositoryFile(
            f"deployment-file-{path.replace('/', '-')}",
            repository=repository.name,
            branch=default_branch,
            file=path,
            content=_render(
                path,
                site=site,
                namespace=namespace,
                chart_version=chart_version,
                release_name=release_name,
            ),
            commit_message=f"Bootstrap {path}",
            commit_author="Pulumi",
            commit_email="pulumi@aridhia.com",
            overwrite_on_create=True,
            opts=pulumi.ResourceOptions(provider=provider, depends_on=[repository]),
        )

    pulumi.export("repository", repository.html_url)
    pulumi.export("site", site)
    pulumi.export("namespace", namespace)
    return repository
