import re
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Relationship, declarative_base
from flask_sqlalchemy import SQLAlchemy
from app.exceptions import InvalidDBEntry
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
    def get_all(cls):
        ds = db.session.execute(select(cls)).all()
        jsonized = []
        for d in ds:
            jsonized.append(d[0].sanitized_dict())
        return jsonized

    @classmethod
    def _get_fields(cls):
        return [f for f in cls.__dict__.keys() if not re.match(r'^_', f)]

    @classmethod
    def is_field_required(cls, f):
        attribute = getattr(cls, f)
        return not getattr(attribute, 'nullable', True) and f != 'id' and isinstance(attribute.prop, Relationship)

    @classmethod
    def _get_required_fields(cls):
        return [f for f in cls._get_fields() if cls.is_field_required(f)]

    @classmethod
    def validate(cls, data:dict):
        """
        Make sure we have all required fields. Set to None if missing
        """
        if not data:
            raise InvalidDBEntry(f"No usable data foundfor table {cls.__tablename__}")
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
