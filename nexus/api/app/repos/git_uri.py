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


def normalise_provider_uri(uri: str) -> str:
    """
    The one form a git provider's web address is kept in: scheme://host[:port][/path],
    lowercase, with no default port or trailing slash.
    Raises ValueError for anything that is not an http(s) address.
    """
    parsed = urlparse(uri.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Provider uri {uri!r} must use http or https")
    if not parsed.hostname or "@" in parsed.netloc:
        raise ValueError(f"Provider uri {uri!r} must have a host and no credentials")
    return f"{parsed.scheme}://{_netloc_without_default_port(parsed)}{parsed.path.rstrip('/')}".lower()


def normalise_repo_path(repo_path: str) -> str:
    """
    The one form a repository's path on its provider is kept in: owner/name, lowercase,
    with no slash around it or '.git' suffix. Raises ValueError for anything else.
    """
    path = repo_path.strip().strip("/").removesuffix(".git").lower()
    segments = path.split("/")
    if len(segments) != 2 or not all(segments):
        raise ValueError(f"Repository path {repo_path!r} must be of the form owner/name")
    return path


def validate_api_uri(api_uri: str, uri: str) -> str:
    """
    A provider's API base URL must be http(s), carry no credentials and be on the
    provider's own host and port (api.github.com for github.com), as the repository
    tokens are sent to it. The uri is the normalised provider uri.
    Raises ValueError for any other api_uri.
    """
    parsed = urlparse(api_uri.strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"api_uri {api_uri!r} must use http or https")
    if not parsed.hostname or "@" in parsed.netloc:
        raise ValueError(f"api_uri {api_uri!r} must have a host and no credentials")
    provider_host = urlparse(uri).netloc
    expected = "api.github.com" if provider_host == "github.com" else provider_host
    if _netloc_without_default_port(parsed).lower() != expected:
        raise ValueError(f"api_uri {api_uri!r} must be on the host {expected}")
    return api_uri
