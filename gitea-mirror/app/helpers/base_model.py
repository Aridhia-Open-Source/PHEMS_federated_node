from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from flask_sqlalchemy import SQLAlchemy

from app.helpers.const import build_sql_uri

engine = create_engine(build_sql_uri())
Base = declarative_base()
db = SQLAlchemy(model_class=Base)
