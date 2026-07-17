from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime as dt
from datetime import timezone as tz

from sqlalchemy import Column, DateTime, Integer, String, func
from sqlalchemy.orm import relationship
from app.helpers.base_model import BaseModel, db
from app.models import Models


def epoch_ts():
    return dt.fromtimestamp(0, tz=tz.utc)


class Repository(db.Model, BaseModel):
    __tablename__ = 'repositories'

    id = Column(Integer, primary_key=True, autoincrement=True)
    uri = Column(String(4096), unique=True, nullable=False)
    watch_dir = Column(String(4096), nullable=False)
    base_branch = Column(String(256), nullable=False, default='main')
    polled_at = Column(DateTime, nullable=True)

    datasets = relationship("Dataset", back_populates="repository")
    pull_requests = relationship("PullRequest", back_populates="repository", cascade="all, delete")

    @property
    def path(self):
        return str(Path(urlparse(str(self.uri)).path)).strip('/')

    def get_last_merged_at(self) -> str:
        """Get latest PR merge time from all ingested pull requests."""
        latest = db.session.query(func.max(Models.PullRequest.merged_at))\
            .filter_by(repository_id=self.id)\
            .scalar()

        return (latest or epoch_ts()).strftime("%Y-%m-%dT%H:%M:%SZ")

    def sanitized_dict(self):
        return {
            'id': self.id,
            'uri': self.uri,
            'path': self.path,
            'watch_dir': self.watch_dir,
            'base_branch': self.base_branch,
            'last_merged_at': self.get_last_merged_at(),
            'pull_request_count': len(self.pull_requests)
        }

    def __init__(self, uri: str, watch_dir: str, base_branch: str = 'main', pr_cursor: int = 0):
        self.uri = uri.lower()
        self.pr_cursor = pr_cursor
        self.watch_dir = watch_dir
        self.base_branch = base_branch

    def __repr__(self):
        return f'<Repository ({self.uri})>'
