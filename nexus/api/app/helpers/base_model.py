import math
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Self

from sqlalchemy import Column, create_engine
from sqlalchemy.orm import Query, Relationship, declarative_base, scoped_session, sessionmaker

from app.helpers.const import build_sql_uri
from app.helpers.exceptions import DBRecordNotFoundError, InvalidDBEntry

engine = create_engine(build_sql_uri())
Base = declarative_base()

# Set per request by the session middleware (app/middleware.py). Unset outside a request: fail fast.
request_scope: ContextVar = ContextVar("request_scope")
session = scoped_session(sessionmaker(bind=engine), scopefunc=request_scope.get)
Base.query = session.query_property()


class Database:
    """What the models and helpers copied from the webserver reach through `db`."""
    session = session
    Model = Base


db = Database()


@dataclass
class Page:
    items: list
    page: int
    per_page: int
    total: int

    @property
    def pages(self) -> int:
        return math.ceil(self.total / self.per_page) if self.per_page else 0


def paginate(query: Query, page: int, per_page: int) -> Page:
    """Replaces Flask-SQLAlchemy's .paginate(error_out=False), which clamps a page below 1 to 1 and a
    per_page below 1 to 20."""
    page = max(page, 1)
    per_page = per_page if per_page >= 1 else 20
    return Page(
        items=query.limit(per_page).offset((page - 1) * per_page).all(),
        page=page, per_page=per_page, total=query.order_by(None).count(),
    )


# Another helper class for common methods
class BaseModel:
    WIRE_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

    @classmethod
    def _query(cls, page: int, per_page: int, **filters) -> Page:
        return paginate(cls.query.filter_by(**filters), page, per_page)

    def add(self, commit=True):
        db.session.add(self)
        db.session.flush()
        if commit:
            db.session.commit()

    def delete(self, commit=True):
        db.session.delete(self)
        db.session.flush()
        if commit:
            db.session.commit()

    @classmethod
    def get_all(cls, page: int, per_page: int, **filters) -> Page:
        return cls._query(page, per_page, **filters)

    @classmethod
    def _get_fields(cls) -> list[Column]:
        return cls.__table__.columns._all_columns

    @classmethod
    def _get_fields_name(cls) -> list[str]:
        return [col.name for col in cls._get_fields()]

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
    def _get_required_fields(cls) -> list[str]:
        return [f.name for f in cls._get_fields() if cls.is_field_required(f)]

    @classmethod
    def validate(cls, data: dict) -> dict:
        """
        Make sure we have all required fields. Set to None if missing
        """
        if not data:
            raise InvalidDBEntry(f"No usable data found for table {cls.__tablename__}")
        valid = data.copy()
        for k, v in data.items():
            field = getattr(cls, k, None)
            if field is None or isinstance(v, (dict, list)) or isinstance(field.property, Relationship):
                continue
            if getattr(cls, k).nullable:
                valid[k] = v
            elif v is None:
                raise InvalidDBEntry(f"Field {k} has invalid value")
        for req_field in cls._get_required_fields():
            if req_field not in list(valid.keys()):
                raise InvalidDBEntry(f"Field \"{req_field}\" missing")
        return valid

    @classmethod
    def get_by_id(cls, obj_id: int) -> Self:
        """
        Common wrapper to get by id, and raise an
        exception if not found
        """
        obj = cls.query.filter(cls.id == obj_id).one_or_none()
        if obj is None:
            raise DBRecordNotFoundError(f"{cls.__name__.capitalize()} with id {obj_id} does not exist")
        return obj
