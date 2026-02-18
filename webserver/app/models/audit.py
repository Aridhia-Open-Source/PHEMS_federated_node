from sqlalchemy import Column, Integer, DateTime, String
from sqlalchemy.sql import func
from app.helpers.base_model import BaseModel, db


class Audit(db.Model, BaseModel):
    __tablename__ = 'audit'
    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_address = Column(String(256), nullable=False)
    http_method = Column(String(256), nullable=False)
    endpoint = Column(String(256), nullable=False)
    requested_by = Column(String(256), nullable=False)
    status_code = Column(Integer)
    api_function = Column(String(256))
    details = Column(String(4096))
    event_time = Column(DateTime(timezone=False), server_default=func.now())
