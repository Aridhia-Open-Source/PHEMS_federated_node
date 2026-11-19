"""
The backend's ids for what a node file names, found by the same normalised keys the diff compares by. `apply` and
`delete` need them for every request, and the entity has to be there: an earlier step made it, or the diff saw it.
"""

from app.git_uri import normalise_provider_uri
from fncli.backend import FncliBackendAPI


def present(value, what: str):
    """An entity that is expected to be in the backend"""
    if value is None:
        raise RuntimeError(f"{what} is not in the backend")
    return value


def provider_id(api: FncliBackendAPI, uri: str) -> int:
    providers = api.get_git_providers()
    return present(next((p for p in providers if normalise_provider_uri(p.uri) == uri), None), f"provider {uri}").id


def repository_id(api: FncliBackendAPI, entity: str, uri: str) -> int:
    find = api.find_trigger_repository if entity == "trigger" else api.find_results_repository
    return present(find(uri), f"{entity} repository {uri}").id


def dataset_id(api: FncliBackendAPI, name: str) -> int:
    return present(api.find_dataset(name), f"dataset {name}").id


def project_id(api: FncliBackendAPI, name: str) -> int:
    return present(api.find_project(name), f"project {name}").id
