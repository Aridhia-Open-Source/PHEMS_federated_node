from datetime import datetime
from sqlalchemy import Integer, DateTime, String
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm.properties import MappedColumn
from sqlalchemy.sql import func
from app.helpers.base_model import BaseModel


class Audit(BaseModel):
    __tablename__ = 'audit'
    id: MappedColumn[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ip_address: MappedColumn[str] = mapped_column(String(256), nullable=False)
    http_method: MappedColumn[str] = mapped_column(String(256), nullable=False)
    endpoint: MappedColumn[str] = mapped_column(String(256), nullable=False)
    requested_by: MappedColumn[str] = mapped_column(String(256), nullable=False)
    status_code: MappedColumn[int] = mapped_column(Integer)
    api_function: MappedColumn[str] = mapped_column(String(256))
    details: MappedColumn[str] = mapped_column(String(4096))
    event_time: MappedColumn[datetime] = mapped_column(DateTime(timezone=False), server_default=func.now())
