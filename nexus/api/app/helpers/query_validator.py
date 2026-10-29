"""
Handler for different db engines queries.
At the current state we support:
    - postgresql
    - MS SQL
"""
import logging
import re
import pymssql
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import ProgrammingError, OperationalError, InternalError

from app.helpers.const import build_sql_uri
from app.models.dataset import Dataset
from app.helpers.exceptions import DBError

logger = logging.getLogger('query_validator')
logger.setLevel(logging.INFO)

def connect_to_dataset(dataset:Dataset) -> sessionmaker:
    """
    Given a datasets object, create a connection string
    and return a session that can be used to send queries
    """
    user, passw = dataset.get_credentials()
    if dataset.type == "postgres":
        engine = create_engine(build_sql_uri(
            host=re.sub('http(s)*://', '', dataset.host),
            port=dataset.port,
            username=user,
            password=passw,
            database=dataset.name
        ))
        session = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine
        )
        return session()
    elif dataset.type == "mssql":
        conn = pymssql.connect(host=dataset.host, user=user, password=passw, database=dataset.name, port=dataset.port)
        return conn.cursor(as_dict=True)

def validate(query:str, dataset:Dataset) -> bool:
    """
    Simple method to validate SQL syntax, and against
    the actual dataset.
    """
    try:
        session = connect_to_dataset(dataset)
        if dataset.type == "postgres":
            # Read only query, so things like UPDATE, DELETE or DROP won't be executed
            session.execute(text('SET TRANSACTION READ ONLY'))
            session.execute(text(query)).all()
        if dataset.type == "mssql":
            session.execute(query)
            session.fetchall()
        return True
    except OperationalError as exc:
        logger.info(f"Connection to the DB failed: \n{str(exc)}")
        raise DBError("Could not connect to the database", 500) from exc
    except (ProgrammingError, InternalError) as exc:
        logger.info(f"Query validation failed\n{str(exc)}")
        return False
