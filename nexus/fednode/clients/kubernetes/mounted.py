"""Read mounted Kubernetes Secret files without caching their values."""
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class MountedSecret:
    """Read one credential from a mounted directory, falling back to the environment."""

    def __init__(self, mount_path: str | os.PathLike[str]):
        self.mount_path = Path(mount_path)

    def read(self, name: str, default: str = "") -> str:
        """Read a fresh value so Kubernetes Secret rotations are observed without a restart."""
        path = self.mount_path / name
        try:
            with path.open(encoding="utf-8") as handle:
                return handle.read().strip()
        except FileNotFoundError:
            return os.getenv(name, default)
        except OSError as exc:
            logger.warning("Could not read %s (%s), falling back to the environment", path, exc)
            return os.getenv(name, default)
