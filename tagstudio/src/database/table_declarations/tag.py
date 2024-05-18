from __future__ import annotations

from sqlalchemy import ForeignKey, select
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship
from src.core.json_typing import JsonTag  # type: ignore

from .base import Base
from .joins import tag_subtags


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str]
    shorthand: Mapped[str]

    aliases: Mapped[list[TagAlias]] = relationship(back_populates="tag")

    parent_tags: Mapped[set[Tag]] = relationship(
        secondary=tag_subtags,
        primaryjoin="Tag.id == tag_subtags.c.subtag_id",
        secondaryjoin="Tag.id == tag_subtags.c.parent_tag_id",
        back_populates="subtags",
    )

    subtags: Mapped[set[Tag]] = relationship(
        secondary=tag_subtags,
        primaryjoin="Tag.id == tag_subtags.c.parent_tag_id",
        secondaryjoin="Tag.id == tag_subtags.c.subtag_id",
        back_populates="parent_tags",
    )

    color: Mapped[str]

    @property
    def subtag_ids(self) -> list[int]:
        return [tag.id for tag in self.subtags]

    @property
    def alias_strings(self) -> list[str]:
        return [alias.name for alias in self.aliases]

    def __init__(
        self,
        name: str,
        aliases: list[TagAlias],
        subtags: set[Tag],
        color: str,
        shorthand: str,
    ):
        self.name = name
        self.subtags = subtags
        self.color = color
        self.shorthand = shorthand
        self.aliases = aliases
        super().__init__()

    def __str__(self) -> str:
        return (
            f"\nID: {self.id}\nName: {self.name}\n"
            # TODO
            f"Shorthand: {self.shorthand}\nAliases: {self.alias_strings}\n"
            f"Subtags: {self.subtag_ids}\nColor: {self.color}\n"
        )

    def __repr__(self) -> str:
        return self.__str__()

    def display_name(self) -> str:
        """Returns a formatted tag name intended for displaying."""
        if self.subtag_ids:
            first_subtag = self.subtags.pop()
            first_subtag_display_name = first_subtag.shorthand or first_subtag.name
            return f"{self.name}" f" ({first_subtag_display_name})"
        else:
            return f"{self.name}"

    def compressed_dict(self) -> JsonTag:
        """
        An alternative to __dict__ that only includes fields containing
        non-default data.
        """
        obj: JsonTag = {"id": self.id}
        if self.name:
            obj["name"] = self.name
        if self.shorthand:
            obj["shorthand"] = self.shorthand
        if self.aliases:
            obj["aliases"] = self.alias_strings
        if self.subtag_ids:
            obj["subtag_ids"] = self.subtag_ids
        if self.color:
            obj["color"] = self.color

        return obj

    def add_subtag(self, tag: Tag | int, session: Session):
        if isinstance(tag, int):
            tag_ = session.scalar(select(Tag).where(Tag.id == tag))
            if not tag_:
                raise ValueError
            tag = tag_
        if tag not in self.subtags:
            self.subtags.add(tag)

    def remove_subtag(self, tag: Tag | int, session: Session):
        if isinstance(tag, int):
            tag_ = session.scalar(select(Tag).where(Tag.id == tag))
            if not tag_:
                raise ValueError
            tag = tag_

        if tag in self.subtags:
            self.subtags.remove(tag)


class TagAlias(Base):
    __tablename__ = "tag_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str]

    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"))
    tag: Mapped[Tag] = relationship(back_populates="aliases")

    def __init__(self, name: str, tag: Tag | None = None):
        self.name = name

        if tag:
            self.tag = tag

        super().__init__()
