from urllib.parse import urlparse

DEFAULT_PORTS = {"http": 80, "https": 443}


def _netloc_without_default_port(parsed) -> str:
    if parsed.port is not None and parsed.port == DEFAULT_PORTS.get(parsed.scheme):
        return parsed.netloc.removesuffix(f":{parsed.port}")
    return parsed.netloc


def normalise_repo_uri(uri: str) -> str:
    """
    The one form a repository URI is kept in: host[:port]/path, lowercase, with no scheme,
    default port (:443 for https, :80 for http), trailing slash or '.git' suffix.
    Accepts 'host/owner/repo' as well as an http(s) URL.
    Raises ValueError for anything that is not a repository address.
    """
    parsed = urlparse(uri.strip() if "://" in uri else f"//{uri.strip()}")
    if parsed.scheme not in ("", "http", "https"):
        raise ValueError(f"Repository uri {uri!r} must use http or https")
    if not parsed.hostname or "@" in parsed.netloc:
        raise ValueError(f"Repository uri {uri!r} must have a host and no credentials")
    path = parsed.path.rstrip("/").removesuffix(".git")
    if len([segment for segment in path.split("/") if segment]) < 2:
        raise ValueError(f"Repository uri {uri!r} must be of the form host/owner/repo")
    return (_netloc_without_default_port(parsed) + path).lower()


def validate_api_uri(api_uri: str, uri: str) -> str:
    """
    A repository's API base URL must be http(s), carry no credentials and be on the
    repository's own host and port (api.github.com for github.com), as the repository
    token is sent to it. The uri is the normalised repository uri.
    Raises ValueError for any other api_uri.
    """
    parsed = urlparse(api_uri.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"api_uri {api_uri!r} must use http or https")
    if not parsed.hostname or "@" in parsed.netloc:
        raise ValueError(f"api_uri {api_uri!r} must have a host and no credentials")
    repo_host = uri.split("/")[0]
    expected = "api.github.com" if repo_host == "github.com" else repo_host
    if _netloc_without_default_port(parsed).lower() != expected:
        raise ValueError(f"api_uri {api_uri!r} must be on the host {expected}")
    return api_uri
