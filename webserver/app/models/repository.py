import urllib.parse
from typing import cast
from datetime import datetime as dt
from datetime import timezone as tz

from sqlalchemy import Column, DateTime, Integer, String, func
from sqlalchemy.orm import relationship, validates
from app.helpers.base_model import BaseModel, db
from app.models import Models


def now_ts():
    return dt.now(tz=tz.utc)


class Repository(db.Model, BaseModel):
    __tablename__ = 'repositories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uri = Column(String(4096), unique=True, nullable=False)
    watch_dir = Column(String(4096), nullable=False)
    base_branch = Column(String(256), nullable=False, default='main')
    default_dataset_name = Column(String(256), nullable=True)
    initial_cursor = Column(DateTime, default=now_ts)
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(DateTime(timezone=False), server_default=func.now(), onupdate=func.now())

    datasets = relationship("Dataset", back_populates="repository")
    pull_requests = relationship("PullRequest", back_populates="repository", cascade="all, delete")

    @validates('uri')
    def validate_uri(self, key, value):
        """Strip http/https schema from URI on save/update."""
        if value:
            value = self.parse_repo_uri(value)
        return value

    @validates('initial_cursor')
    def validate_initial_cursor(self, key, value):
        """Convert ISO 8601 string to datetime if needed."""
        if isinstance(value, str):
            try:
                value = dt.fromisoformat(value.rstrip('Z'))
            except (ValueError, TypeError):
                raise ValueError("initial_cursor must be a valid ISO 8601 datetime string")

        if self.id is not None and self.pull_requests:
            raise ValueError(
                "Cannot change initial_cursor while pull requests exist. "
                "Delete all pull requests first if you want to adjust the cursor."
            )

        return value

    @property
    def path(self):
        return '/'.join(self.uri.split('/')[1:])

    @classmethod
    def parse_repo_uri(cls, uri: str) -> str:
        """
        Parse the repository URI to extract the host and path.
        """
        parsed = urllib.parse.urlparse(uri)
        return (parsed.netloc + parsed.path).lower().rstrip('/')

    def get_pull_request_cursor(self) -> str:
        """
        Get latest PR merge time from all ingested pull requests.
        If no pull requests exist, use initial_cursor as the starting point.
        """
        pr_cursor = db.session.query(func.max(Models.PullRequest.merged_at))\
            .filter_by(repository_id=self.id)\
            .scalar()

        initial_cursor = cast(dt, self.initial_cursor)

        return (pr_cursor or initial_cursor).strftime("%Y-%m-%dT%H:%M:%SZ")

    def sanitized_dict(self):
        return {
            'id': self.id,
            'uri': self.uri,
            'path': self.path,
            'watch_dir': self.watch_dir,
            'base_branch': self.base_branch,
            'default_dataset_name': self.default_dataset_name,
            'pr_cursor': self.get_pull_request_cursor(),
            'pr_count': len(self.pull_requests)
        }

    def __init__(
        self,
        uri: str,
        watch_dir: str,
        base_branch: str = 'main',
        default_dataset_name: str | None = None,
        initial_cursor: dt | None = None,
    ):
        self.uri = uri
        self.watch_dir = watch_dir
        self.base_branch = base_branch
        self.default_dataset_name = default_dataset_name
        self.initial_cursor = initial_cursor

    def __repr__(self):
        return f'<Repository ({self.uri})>'
