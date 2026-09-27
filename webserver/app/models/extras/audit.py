from datetime import datetime as dt

import sqlalchemy as sa
from sqlalchemy.sql import func

from app.helpers.base_model import BaseModel, db


class Audit(db.Model, BaseModel):
    __tablename__ = 'audit'

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    ip_address = sa.Column(sa.String(256), nullable=False)
    http_method = sa.Column(sa.String(256), nullable=False)
    endpoint = sa.Column(sa.String(256), nullable=False)
    requested_by = sa.Column(sa.String(256), nullable=False)
    status_code = sa.Column(sa.Integer, nullable=True)
    api_function = sa.Column(sa.String(256), nullable=True)
    details = sa.Column(sa.String(4096), nullable=True)
    event_time = sa.Column(sa.DateTime(timezone=False), server_default=func.now())

    def __init__(
        self,
        ip_address: str,
        http_method: str,
        endpoint: str,
        requested_by: str,
        status_code: int | None = None,
        api_function: str | None = None,
        details: str | None = None
    ):
        self.ip_address = ip_address
        self.http_method = http_method
        self.endpoint = endpoint
        self.requested_by = requested_by
        self.status_code = status_code
        self.api_function = api_function
        self.details = details
        self.event_time = dt.now()
