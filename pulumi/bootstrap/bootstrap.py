"""Pulumi resources for an environment's GitHub deployment repository.

The repository is deliberately the boundary between infrastructure and Flux:
Pulumi creates the repository and its initial declarative files, while Flux
reads and applies the committed files in each environment's cluster.
"""

from pathlib import Path
import re

import pulumi
import pulumi_github as github


ROOT = Path(__file__).parent
DEFAULT_CHART_VERSION = "2.0.0"
PLACEHOLDER = re.compile(r"{{[^{}]+}}")
ENVIRONMENT = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
TEMPLATE_FILES = (
    "README.md",
    "kustomization.yaml",
    "namespaces.yaml",
    "helmrepository.yaml",
    "helmrelease.yaml",
    "values.yaml",
    "kustomizeconfig.yaml",
)


def parse_environments(value: str) -> tuple[str, ...]:
    """Parse and validate the comma-separated deployment environments."""

    environments = tuple(item.strip() for item in value.split(","))
    if not environments or any(not item for item in environments):
        raise ValueError("environments must contain one or more comma-separated values")

    invalid = [item for item in environments if not ENVIRONMENT.fullmatch(item)]
    if invalid:
        raise ValueError(f"invalid environment name(s): {invalid}")

    duplicates = sorted({item for item in environments if environments.count(item) > 1})
    if duplicates:
        raise ValueError(f"duplicate environment name(s): {duplicates}")
    return environments


def deployment_files(environments: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """Return repository paths and their source templates."""

    return tuple(
        (f"clusters/{environment}/{template}", template)
        for environment in environments
        for template in TEMPLATE_FILES
    )


def _render(
    path: str,
    *,
    environment: str,
    namespace: str,
    chart_version: str,
    release_name: str,
) -> str:
    content = (ROOT / "files" / path).read_text(encoding="utf-8")
    rendered = (
        content.replace("{{ENVIRONMENT}}", environment)
        .replace("{{NAMESPACE}}", namespace)
        .replace("{{CHART_VERSION}}", chart_version)
        .replace("{{RELEASE_NAME}}", release_name)
    )
    unresolved = PLACEHOLDER.findall(rendered)
    if unresolved:
        raise ValueError(f"unresolved template placeholders in {path}: {unresolved}")
    return rendered


def create_deployment_repository() -> github.Repository:
    """Create the deployment repository and converge its initial files."""

    config = pulumi.Config()
    owner = pulumi.Config("github").require("owner")
    repository_name = config.get("repository") or "phems-deployment"
    environments = parse_environments(config.get("environments") or "develop")
    namespace = config.get("namespace") or "fn"
    chart_version = config.get("chart-version") or DEFAULT_CHART_VERSION
    release_name = config.get("release-name") or "federated-node"
    commit_author = config.get("commit-author") or "Pulumi"
    commit_email = config.get("commit-email") or "pulumi@aridhia.com"
    default_branch = "main"

    provider = github.Provider("github", owner=owner)
    repository = github.Repository(
        "deployment-repository",
        name=repository_name,
        description=f"PHEMS deployment configuration for {repository_name}",
        visibility="private",
        auto_init=True,
        has_issues=False,
        has_projects=False,
        has_wiki=False,
        delete_branch_on_merge=True,
        opts=pulumi.ResourceOptions(provider=provider),
    )

    # auto_init gives both a new repository and an imported empty repository a
    # commit on main. RepositoryFile is then safe to retry and overwrites only
    # the files owned by this stack.
    previous_file = None
    for path, template in deployment_files(environments):
        environment = path.split("/")[1]
        repository_file = github.RepositoryFile(
            f"deployment-file-{path.replace('/', '-')}",
            repository=repository.name,
            branch=default_branch,
            file=path,
            content=_render(
                template,
                environment=environment,
                namespace=namespace,
                chart_version=chart_version,
                release_name=release_name,
            ),
            commit_message=f"Bootstrap {path}",
            commit_author=commit_author,
            commit_email=commit_email,
            overwrite_on_create=True,
            opts=pulumi.ResourceOptions(
                provider=provider,
                depends_on=[resource for resource in (repository, previous_file) if resource],
            ),
        )
        previous_file = repository_file

    pulumi.export("repository", repository.html_url)
    pulumi.export("environments", environments)
    pulumi.export("namespace", namespace)
    return repository
