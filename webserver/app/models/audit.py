from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, String
from sqlalchemy.sql import func
from app.helpers.db import BaseModel, db

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

    def __init__(self,
                 ip_address:str,
                 http_method:str,
                 endpoint:str,
                 requested_by:str,
                 status_code:int,
                 api_function:str,
                 details:str
                ):
        self.ip_address = ip_address
        self.http_method = http_method
        self.endpoint = endpoint
        self.requested_by = requested_by
        self.status_code = status_code
        self.api_function = api_function
        self.details = details
        self.event_time = datetime.now()
