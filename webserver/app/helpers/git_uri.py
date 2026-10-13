from urllib.parse import urlparse


def normalise_repo_uri(uri: str) -> str:
    """
    The one form a repository URI is kept in: host[:port]/path, lowercase, with no scheme,
    trailing slash or '.git' suffix. Accepts 'host/owner/repo' as well as an http(s) URL.
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
    return (parsed.netloc + path).lower()
