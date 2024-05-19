from pathlib import Path
from typing import Sequence, TypeVar

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from src.database.table_declarations.entry import Entry  # type: ignore
from src.database.table_declarations.field import (  # type: ignore
    DatetimeField,
    TagBoxField,
    TextField,
)
from src.database.table_declarations.tag import Tag  # type: ignore

Queryable = TypeVar("Queryable", Tag, Entry, TextField, DatetimeField, TagBoxField)


def path_in_db(path: Path, engine: Engine) -> bool:
    with Session(engine) as session, session.begin():
        result = session.execute(
            select(Entry.id).where(Entry.path == path)
        ).one_or_none()

        result_bool = bool(result)

    return result_bool


def get_object_by_id(id: int, type: Queryable, engine: Engine) -> Queryable:
    with Session(engine) as session, session.begin():
        result: Queryable | None = session.scalar(select(type).where(type.id == id))  # type: ignore

        if result is None:
            raise ValueError(f"No {type} with id {id} found.")

        session.expunge(result)

    return result


def get_objects_by_ids(
    ids: Sequence[int],
    type: Queryable,
    engine: Engine,
) -> list[Queryable]:
    with Session(engine) as session, session.begin():
        results: list[Queryable] = list(
            session.scalars(select(type).where(type.id.in_(ids))).all()  # type: ignore
        )

        session.expunge(results)

    return results
