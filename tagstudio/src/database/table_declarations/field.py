from __future__ import annotations

import datetime
from enum import Enum
from typing import TYPE_CHECKING, Union

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .joins import tag_fields

if TYPE_CHECKING:
    from .entry import Entry
    from .tag import Tag

Field = Union["TextField", "TagBoxField", "DatetimeField"]


class TextFieldTypes(Enum):
    text_line = "Text Line"
    text_box = "Text Box"


class TagBoxTypes(Enum):
    tag_box = "Tags"


class DateTimeTypes(Enum):
    date = "Date"
    date_taken = "Date Taken"
    date_created = "Date Created"
    date_modified = "Date Modified"
    date_published = "Date Published"
    date_uploaded = "Date Uploaded"
    date_released = "Date Released"


class TextField(Base):
    __tablename__ = "text_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[TextFieldTypes]

    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    entry: Mapped[Entry] = relationship()

    value: Mapped[str | None]

    def __init__(
        self,
        type: TextFieldTypes,
        value: str | None = None,
        entry: Entry | None = None,
    ):
        self.type = type
        self.value = value

        if entry:
            self.entry = entry
        super().__init__()


class TagBoxField(Base):
    __tablename__ = "tag_box_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[TagBoxTypes] = mapped_column(default=TagBoxTypes.tag_box)

    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    entry: Mapped[Entry] = relationship()

    tags: Mapped[set[Tag]] = relationship(secondary=tag_fields)

    def __init__(
        self,
        tags: set[Tag],
        entry: Entry | None = None,
        type: TagBoxTypes = TagBoxTypes.tag_box,
    ):
        self.tags = tags
        self.type = type

        if entry:
            self.entry = entry
        super().__init__()


class DatetimeField(Base):
    __tablename__ = "datetime_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[DateTimeTypes]

    entry_id: Mapped[int] = mapped_column(ForeignKey("entries.id"))
    entry: Mapped[Entry] = relationship()

    value: Mapped[datetime.datetime]

    def __init__(
        self,
        value: datetime.datetime,
        type: DateTimeTypes,
        entry: Entry | None = None,
    ):
        self.type = type
        self.value = value

        if entry:
            self.entry = entry
        super().__init__()
