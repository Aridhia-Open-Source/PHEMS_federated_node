from contextlib import contextmanager
from datetime import datetime
from flask import request
from typing import Any, Generator, Self
from flask_sqlalchemy.pagination import QueryPagination
from sqlalchemy import create_engine, Column, select
from sqlalchemy.orm import DeclarativeBase, Relationship, Session, sessionmaker
from app.helpers.exceptions import DBRecordNotFoundError, InvalidDBEntry, InvalidRequest
from app.helpers.const import build_sql_uri


engine = create_engine(build_sql_uri())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@contextmanager
def get_db() -> Generator[Session, Any, None]:
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Another helper class for common methods
class BaseModel(DeclarativeBase):
    @classmethod
    def _query(cls) -> QueryPagination:
        try:
            page = int(request.values.get("page", '1'))
            per_page = int(request.values.get("per_page", '25'))
        except ValueError as ve:
            raise InvalidRequest("page and per_page parameters should be integers") from ve

        return cls.query.paginate(page=page, per_page=per_page)

    def sanitized_dict(self) -> dict[str, bool|int|str]:
        """
        Based on the list of column names, conditionally render the values
        in a dictionary
        """
        jsonized = {}
        for field in self._get_fields_name():
            val = getattr(self, field)
            match val:
                case int() | bool() | None:
                    jsonized[field] = val
                case datetime():
                    jsonized[field] = val.strftime("%Y-%m-%d %H:%M:%S")
                case BaseModel():
                    pass
                case _:
                    jsonized[field] = str(val)
        return jsonized

    def add(self, session: Session, commit:bool=True) -> None:
        session.add(self)
        session.commit()
        session.refresh(self, attribute_names=["id"])

    def update(self, session:Session, data: dict) -> None:
        """
        Should help in managing instances created in other sessions
        """
        persistent_self = session.merge(self)
        for key, value in data.items():
            setattr(persistent_self, key, value)

        session.flush()
        session.refresh(persistent_self)
        for key in data:
            setattr(self, key, getattr(persistent_self, key))

    def delete(self, session:Session, commit=True) -> None:
        session.delete(self)
        if commit:
            session.commit()

    @classmethod
    def get_all(cls, session) -> list[dict]:
        return session.execute(select(cls)).scalars().all()

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
    def validate(cls, data:dict) -> dict:
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

    @classmethod
    def get_by_id(cls, session: Session, obj_id:int, raise_if_not_found:bool = True) -> Self:
        """
        Common wrapper to get by id, and raise an
        exception if not found
        """
        q = select(cls).where(cls.id == obj_id)
        obj = session.execute(q).scalars().one_or_none()
        if obj is None and raise_if_not_found:
            raise DBRecordNotFoundError(f"{cls.__name__.capitalize()} with id {obj_id} does not exist")
        return obj
