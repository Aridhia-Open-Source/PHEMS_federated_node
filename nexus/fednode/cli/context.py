"""
The context file, bootstrap/context.yaml (ContextFile): which node fncli talks to, and the defaults of the commands.
Its `node` block is the node and nothing else, and fncli refuses to run when kubectl points at another cluster. Its
`env_file` holds the node's deploy settings (NAMESPACE, ...). Its `defaults` say which project and way to trigger a
task the commands use when not told. The node's config itself is the fn.aridhia.com resources in config/, applied
with kubectl (ADR 0032).
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import click
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

TRIGGER_TYPES = ("pr", "api")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    """bootstrap/context.yaml: the node fncli talks to, and the defaults of the commands"""

    node: NodeSpec
    defaults: Defaults = Field(default_factory=Defaults)


@dataclass(frozen=True)
class Context:
    """The context file: where it is, the node it names, and the defaults, the env's FNCLI_DEFAULT_* already over them"""

    path: Path
    node: NodeSpec
    defaults: Defaults


class UniqueKeyLoader(yaml.SafeLoader):
    """A mapping with the same key twice is an error, not the last one winning"""

    def construct_mapping(self, node, deep=False):
        keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
        duplicates = sorted({str(key) for key in keys if keys.count(key) > 1})
        if duplicates:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate keys: {', '.join(duplicates)}", node.start_mark
            )
        return super().construct_mapping(node, deep=deep)


def where(loc: tuple) -> str:
    """A pydantic error location as a path in the file: node.kube_context"""
    parts = [part for i, part in enumerate(loc) if not (i + 1 < len(loc) and loc[i + 1] == part) and part != "invalid"]
    text = ""
    for part in parts:
        text += f"[{part}]" if isinstance(part, int) else f".{part}" if text else str(part)
    return text or "the file"


def fail(path: Path, problems: list[str]):
    listing = "\n".join(f"  - {problem}" for problem in problems)
    raise click.ClickException(f"{path} has {len(problems)} problem{'s' * (len(problems) != 1)}:\n{listing}")


def read_yaml(path: Path):
    try:
        return yaml.load(path.read_text(), Loader=UniqueKeyLoader)
    except yaml.YAMLError as error:
        raise click.ClickException(f"{path} is not valid YAML: {error}") from error


def validate(path: Path, model, data):
    try:
        return model.model_validate(data)
    except ValidationError as error:
        # loc and msg only: an error's input could be a value that was not meant to be in the file
        fail(path, [f"{where(e['loc'])}: {e['msg'].removeprefix('Value error, ')}" for e in error.errors()])


def resolve_env_file(spec: NodeSpec, base_dir: Path):
    """
    The env file is looked for from the context file's directory up, so `.dev.env` finds the repo root's; one not found
    is left as written, for open_target to report.
    """
    if spec.env_file is not None:
        env_file = spec.env_file.expanduser()
        found = next((d / env_file for d in (base_dir, *base_dir.parents) if (d / env_file).is_file()), None)
        spec.env_file = found or env_file


def load_context(path: Path) -> Context:
    """The context file, its env file looked for from its directory up, and its defaults under the env's"""
    file = validate(path, ContextFile, read_yaml(path))
    resolve_env_file(file.node, path.resolve().parent)
    project = os.environ.get("FNCLI_DEFAULT_PROJECT") or file.defaults.project
    trigger_type = os.environ.get("FNCLI_DEFAULT_TRIGGER_TYPE") or file.defaults.trigger_type
    if trigger_type is not None and trigger_type not in TRIGGER_TYPES:
        raise click.ClickException(f"The default trigger type must be one of {', '.join(TRIGGER_TYPES)}, not {trigger_type}")
    return Context(path, file.node, Defaults(project=project, trigger_type=trigger_type))
