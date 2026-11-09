"""
The node file (DESIGN-node-file.md, section 2): a YAML file that describes part of a node's desired state, with no
secret values in it. Global resources come first (providers, secrets, repositories, datasets), then the projects,
which hold only assignments of them. Both levels use the same names: `datasets`, and `repositories` with `triggers`
and `results`. A file may hold any of these sections: what it names but does not hold is looked up on the node.

Which node is not in these files: it is in the context file, bootstrap/context.yaml (ContextFile), whose `node` block is
the node fncli talks to and nothing else, and it refuses to run when kubectl points at another cluster. Its `env_file`
holds the values that secret `env` references read, for that node. Its `defaults` say which project and way to
trigger a task the commands use when not told.

A secret says where fncli reads each value at apply time, never the value. A reference is a mapping with one key:

    {env: NAME}                                    an environment variable
    {file: PATH}                                   a file; `~` and a path relative to the node file work
    {k8s_secret: {name: N, namespace: NS, key: K}} a key of a Kubernetes secret
    {generate: {length: 24}}                       a random value (dev only, for stand-in dataset credentials)

and a whole secret may instead be `gitea_oauth: {app: NAME}`, an OAuth app fncli creates and authorises in Gitea.
A bare string where a reference belongs is an error.

A project's datasets and repositories, and a repository's or dataset's secret, may be listed in this file or already be
on the node (made by another file): the diff resolves them against the backend, and blocks what is in neither.

Repository uris are kept in their normalised form (host[:port]/owner/repo, lowercase, no scheme), a provider's uri in
its own (scheme://host[:port]).
"""

from pathlib import Path
from typing import Annotated, Literal, Union
from urllib.parse import urlparse

from pydantic import (
    BaseModel, ConfigDict, Discriminator, Field, Tag, field_validator, model_validator,
)

from app.git_uri import normalise_provider_uri, normalise_repo_uri, validate_api_uri
from app.github import GH_API_BASE_URL

REFERENCE_KINDS = ("env", "file", "k8s_secret", "generate")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def normalise_dir(directory: str) -> str:
    """
    A directory the way nexus-api compares them: '.' and empty segments and the leading and trailing '/'
    dropped, so `specs/` and `specs` are the same. A '..' segment is refused.
    """
    segments = [segment for segment in directory.split("/") if segment not in ("", ".")]
    if ".." in segments:
        raise ValueError(f"directory {directory!r} must not contain '..'")
    return "/".join(segments)


def dirs_overlap(a: str, b: str) -> bool:
    """Whether one directory is the other or inside it (nexus-api's rule for a watch_dir and a target_dir)"""
    segments_a = [segment for segment in normalise_dir(a).split("/") if segment]
    segments_b = [segment for segment in normalise_dir(b).split("/") if segment]
    shorter = min(len(segments_a), len(segments_b))
    return segments_a[:shorter] == segments_b[:shorter]


class EnvRef(Strict):
    env: str = Field(min_length=1)


class FileRef(Strict):
    file: Path


class K8sSecretSource(Strict):
    name: str = Field(min_length=1)
    namespace: str = Field(min_length=1)
    key: str = Field(min_length=1)


class K8sSecretRef(Strict):
    k8s_secret: K8sSecretSource


class GenerateOptions(Strict):
    length: int = Field(default=24, ge=8)


class GenerateRef(Strict):
    generate: GenerateOptions


class InvalidRef(BaseModel):
    """What anything that is not a one-key mapping of a known kind is read as, so the error says what is expected."""

    @model_validator(mode="before")
    @classmethod
    def refuse(cls, value):
        raise ValueError(
            f"a secret value is never written in the file: give a mapping with one key of {', '.join(REFERENCE_KINDS)}, "
            "such as {env: NAME}"
        )


def reference_kind(value) -> str:
    if isinstance(value, dict) and len(value) == 1:
        (kind,) = value
        if kind in REFERENCE_KINDS:
            return kind
    return "invalid"


ValueRef = Annotated[
    Union[
        Annotated[EnvRef, Tag("env")],
        Annotated[FileRef, Tag("file")],
        Annotated[K8sSecretRef, Tag("k8s_secret")],
        Annotated[GenerateRef, Tag("generate")],
        Annotated[InvalidRef, Tag("invalid")],
    ],
    Discriminator(reference_kind),
]


class GiteaOAuth(Strict):
    app: str = Field(min_length=1)


class SecretSpec(Strict):
    """Either `values` (key -> reference) or `gitea_oauth`, not both"""

    values: dict[str, ValueRef] | None = None
    gitea_oauth: GiteaOAuth | None = None

    @model_validator(mode="after")
    def exactly_one_source(self):
        if (self.values is None) == (self.gitea_oauth is None):
            raise ValueError("a secret has exactly one of values and gitea_oauth")
        if self.values is not None and not self.values:
            raise ValueError("values must name at least one key")
        return self


class ProviderSpec(Strict):
    name: str | None = None
    type: Literal["gitea", "github"]
    uri: str
    # github defaults to https://api.github.com; a gitea provider says where its API is
    api_uri: str | None = None

    @field_validator("uri")
    @classmethod
    def normalise_uri(cls, uri: str) -> str:
        return normalise_provider_uri(uri)

    @model_validator(mode="after")
    def api_uri_on_the_providers_host(self):
        if self.api_uri is None:
            if self.type != "github":
                raise ValueError(f"a {self.type} provider needs an api_uri")
            self.api_uri = GH_API_BASE_URL
        validate_api_uri(self.api_uri, self.uri)
        return self

    @property
    def netloc(self) -> str:
        return urlparse(self.uri).netloc

    @property
    def resolved_name(self) -> str:
        """The name it is created under: the one given, else what the env-based setup names it, <type>-<host>"""
        return self.name or f"{self.type}-{self.netloc}"


class RepositorySpec(Strict):
    """A global trigger or results repository, and the secret its git credentials are in"""

    uri: str
    secret: str = Field(min_length=1)

    @field_validator("uri")
    @classmethod
    def normalise_uri(cls, uri: str) -> str:
        return normalise_repo_uri(uri)


class GlobalRepositories(Strict):
    triggers: list[RepositorySpec] = Field(default_factory=list)
    results: list[RepositorySpec] = Field(default_factory=list)


class DatasetSpec(Strict):
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    host: str = Field(min_length=1)
    port: int
    read_schema: str | None = None
    write_schema: str | None = None
    secret: str = Field(min_length=1)


class TriggerAssignment(Strict):
    repository: str
    watch_dir: str
    base_branch: str = Field(min_length=1)
    enabled: bool = True

    @field_validator("repository")
    @classmethod
    def normalise_repository(cls, uri: str) -> str:
        return normalise_repo_uri(uri)

    @field_validator("watch_dir")
    @classmethod
    def watch_a_directory(cls, directory: str) -> str:
        if not normalise_dir(directory):
            raise ValueError("watch_dir must name a directory, not the whole repository")
        return directory


class ResultsAssignment(Strict):
    repository: str
    target_dir: str = Field(min_length=1)
    base_branch: str = Field(min_length=1)
    enabled: bool = True

    @field_validator("repository")
    @classmethod
    def normalise_repository(cls, uri: str) -> str:
        return normalise_repo_uri(uri)

    @field_validator("target_dir")
    @classmethod
    def valid_directory(cls, directory: str) -> str:
        normalise_dir(directory)
        return directory


class ProjectRepositories(Strict):
    triggers: list[TriggerAssignment] = Field(default_factory=list)
    # Exactly one: a project has one results repository
    results: ResultsAssignment

    @model_validator(mode="before")
    @classmethod
    def one_results(cls, value):
        if isinstance(value, dict) and isinstance(value.get("results"), list):
            raise ValueError("a project has exactly one results repository: give `results` as a mapping, not a list")
        return value


class ProjectSpec(Strict):
    name: str = Field(min_length=1)
    # Created disabled, and enabled last
    enabled: bool = True
    # Names of datasets, in this file or on the node. The first becomes the project's default.
    datasets: list[str] = Field(default_factory=list)
    repositories: ProjectRepositories


class GiteaSpec(Strict):
    """Opt-in Gitea admin bootstrap: the OAuth apps of `gitea_oauth` secrets, and optionally the repositories"""

    provider: str = Field(min_length=1)
    create_repositories: bool = False


class NodeSpec(Strict):
    """The node, as this host reaches it"""

    url: str = Field(min_length=1)                      # nexus-api
    kube_context: str = Field(min_length=1)             # where cluster secrets are read from
    keycloak_namespace: str = Field(min_length=1)       # where fncli's login is read from
    gitea_admin_user: str = Field(default="gitea_admin", min_length=1)
    env_file: Path | None = None                        # found from the context file's directory up, like .dev.env


class Defaults(Strict):
    """What the commands use when not told: FNCLI_DEFAULT_PROJECT and FNCLI_DEFAULT_TRIGGER_TYPE win over these"""

    project: str | None = None
    trigger_type: Literal["pr", "api"] | None = None


class ContextFile(Strict):
    """bootstrap/context.yaml: the node every other file is applied to, and the defaults of the commands"""

    node: NodeSpec
    defaults: Defaults = Field(default_factory=Defaults)


class NodeFile(Strict):
    version: Literal[1]
    providers: list[ProviderSpec] = Field(default_factory=list)
    secrets: dict[str, SecretSpec] = Field(default_factory=dict)
    repositories: GlobalRepositories = Field(default_factory=GlobalRepositories)
    datasets: list[DatasetSpec] = Field(default_factory=list)
    projects: list[ProjectSpec] = Field(default_factory=list)
    gitea: GiteaSpec | None = None

    def provider_for(self, repository_uri: str) -> ProviderSpec | None:
        """The provider whose host the (normalised) repository uri is on"""
        host = repository_uri.split("/")[0]
        return next((provider for provider in self.providers if provider.netloc == host), None)
