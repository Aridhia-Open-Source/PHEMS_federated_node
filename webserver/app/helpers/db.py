from sqlalchemy import create_engine, select, Column
from sqlalchemy.orm import Relationship, declarative_base
from flask_sqlalchemy import SQLAlchemy
from app.helpers.exceptions import InvalidDBEntry
from app.helpers.const import build_sql_uri


engine = create_engine(build_sql_uri())
Base = declarative_base()
db = SQLAlchemy(model_class=Base)

# Another helper class for common methods
class BaseModel():
    def sanitized_dict(self):
        jsonized = self.__dict__.copy()
        jsonized.pop('_sa_instance_state', None)
        return jsonized

    def add(self, commit=True):
        db.session.add(self)
        db.session.flush()
        if commit:
            db.session.commit()

    @classmethod
    def get_all(cls) -> list:
        ds = db.session.execute(select(cls)).all()
        jsonized = []
        for d in ds:
            jsonized.append(d[0].sanitized_dict())
        return jsonized

    @classmethod
    def _get_fields(cls) -> list[Column]:
        return cls.__table__.columns._all_columns

    @classmethod
    def is_field_required(cls, attribute: Column) -> bool:
        """
        Generalized check for a column to be required in a request body
        The column, to be required, needs to:
            - not be nullable
            - not have a default value
            - not be a primary key (e.g. id is not allowed as a request body)
        """
        return not (attribute.nullable or attribute.primary_key or attribute.server_default is not None)

    @classmethod
    def _get_required_fields(cls):
        return [f.name for f in cls._get_fields() if cls.is_field_required(f)]

    @classmethod
    def validate(cls, data:dict):
        """
        Make sure we have all required fields. Set to None if missing
        """
        if not data:
            raise InvalidDBEntry(f"No usable data found for table {cls.__tablename__}")
        valid = data.copy()
        for k, v in data.items():
            field = getattr(cls, k, None)
            if field is None or isinstance(v, dict) or isinstance(v, list) or isinstance(field.property, Relationship):
                continue
            if getattr(cls, k).nullable:
                valid[k] = v
            elif v is None:
                raise InvalidDBEntry(f"Field {k} has invalid value")
        for req_field in cls._get_required_fields():
            if req_field not in list(valid.keys()):
                raise InvalidDBEntry(f"Field \"{req_field}\" missing")
        return valid
