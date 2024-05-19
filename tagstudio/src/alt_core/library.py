# Copyright (C) 2024 Travis Abendshien (CyanVoxel).
# Licensed under the GPL-3.0 License.
# Created for TagStudio: https://github.com/CyanVoxel/TagStudio

"""The Library object and related methods for TagStudio."""

import datetime
import logging
import os
import time
import typing
from pathlib import Path
from typing import Iterator, cast

from sqlalchemy import select
from sqlalchemy.orm import Session
from src.alt_core import ts_core
from src.alt_core.types import ItemType
from src.core.json_typing import JsonCollation, JsonTag
from src.core.utils.str import strip_punctuation
from src.core.utils.web import strip_web_protocol
from src.database.manage import make_engine, make_tables

from src.database.queries import path_in_db
from src.database.table_declarations.entry import Entry
from src.database.table_declarations.field import Field
from src.database.table_declarations.tag import Tag, TagAlias, TagColor
from typing_extensions import Self

logging.basicConfig(format="%(message)s", level=logging.INFO)
LOGGER = logging.getLogger(__name__)


class Collation:
    """
    A Library Collation Object. Referenced by ID.
    Entries and their Page #s are grouped together in the e_ids_and_paged tuple.
    Sort order is `(filename | title | date, asc | desc)`.
    """

    def __init__(
        self,
        id: int,
        title: str,
        e_ids_and_pages: list[tuple[int, int]],
        sort_order: str,
        cover_id: int = -1,
    ) -> None:
        self.id = int(id)
        self.title = title
        self.e_ids_and_pages = e_ids_and_pages
        self.sort_order = sort_order
        self.cover_id = cover_id
        self.fields = None  # Optional Collation-wide fields. WIP.

    def __str__(self) -> str:
        return f"\n{self.compressed_dict()}\n"

    def __repr__(self) -> str:
        return self.__str__()

    @typing.no_type_check
    def __eq__(self, __value: object) -> bool:
        __value = cast(Self, __value)
        if os.name == "nt":
            return (
                int(self.id) == int(__value.id)
                and self.filename.lower() == __value.filename.lower()
                and self.path.lower() == __value.path.lower()
                and self.fields == __value.fields
            )
        else:
            return (
                int(self.id) == int(__value.id)
                and self.filename == __value.filename
                and self.path == __value.path
                and self.fields == __value.fields
            )

    def compressed_dict(self) -> JsonCollation:
        """
        An alternative to __dict__ that only includes fields containing
        non-default data.
        """
        obj: JsonCollation = {"id": self.id}
        if self.title:
            obj["title"] = self.title
        if self.e_ids_and_pages:
            # TODO: work with tuples
            obj["e_ids_and_pages"] = [list(x) for x in self.e_ids_and_pages]
            # obj['e_ids_and_pages'] = self.e_ids_and_pages
        if self.sort_order:
            obj["sort_order"] = self.sort_order
        if self.cover_id:
            obj["cover_id"] = self.cover_id

        return obj


def library_defaults() -> list[Tag | Field]:
    archive_tag = Tag(
        name="Archived",
        aliases=set([TagAlias(name="Archive")]),
        color=TagColor.red,
    )

    favorite_tag = Tag(
        name="Favorite",
        aliases=set(
            [
                TagAlias(name="Favorited"),
                TagAlias(name="Favorites"),
            ]
        ),
        color=TagColor.yellow,
    )

    # TODO
    """    
    not_implemented = [
        {"id": 10, "name": "Date", "type": "datetime"},
        {"id": 11, "name": "Date Created", "type": "datetime"},
        {"id": 12, "name": "Date Modified", "type": "datetime"},
        {"id": 13, "name": "Date Taken", "type": "datetime"},
        {"id": 14, "name": "Date Published", "type": "datetime"},
        {"id": 22, "name": "Date Uploaded", "type": "datetime"},
        {"id": 23, "name": "Date Released", "type": "datetime"},
        {"id": 15, "name": "Archived", "type": "checkbox"},
        {"id": 16, "name": "Favorite", "type": "checkbox"},
        {"id": 9, "name": "Collation", "type": "collation"},
        {"id": 17, "name": "Book", "type": "collation"},
        {"id": 18, "name": "Comic", "type": "collation"},
        {"id": 19, "name": "Series", "type": "collation"},
        {"id": 20, "name": "Manga", "type": "collation"},
        {"id": 24, "name": "Volume", "type": "collation"},
        {"id": 25, "name": "Anthology", "type": "collation"},
        {"id": 26, "name": "Magazine", "type": "collation"},
    ]
    """

    """
    fields = [
        TextField(name="Title", type=TextFieldTypes.text_line),
        TextField(name="Author", type=TextFieldTypes.text_line),
        TextField(name="Artist", type=TextFieldTypes.text_line),
        TextField(name="Guest Artist", type=TextFieldTypes.text_line),
        TextField(name="URL", type=TextFieldTypes.text_line),
        TextField(name="Source", type=TextFieldTypes.text_line),
        TextField(name="Publisher", type=TextFieldTypes.text_line),
        TextField(name="Composer", type=TextFieldTypes.text_line),
        TextField(name="Description", type=TextFieldTypes.text_box),
        TextField(name="Notes", type=TextFieldTypes.text_box),
        TextField(name="Comments", type=TextFieldTypes.text_box),
        TagBoxField(name="Tags"),
        TagBoxField(name="Content Tags"),
        TagBoxField(name="Meta Tags"),
        DatetimeField(name="Date"),
        DatetimeField(name="Date Created"),
        DatetimeField(name="Date Modified"),
        DatetimeField(name="Date Taken"),
        DatetimeField(name="Date Published"),
        DatetimeField(name="Date Uploaded"),
        DatetimeField(name="Date Released"),
    ]
    """

    return [archive_tag, favorite_tag]


class Library:
    """Class for the Library object, and all CRUD operations made upon it."""

    @property
    def entries(self) -> list[Entry]:
        with Session(self.engine) as session, session.begin():
            entries = list(session.scalars(select(Entry)).all())
            session.expunge_all()
        return entries

    def __init__(self) -> None:
        # Library Info =========================================================
        self.root_path: Path | None = None

        # Entries ==============================================================
        # Map of every Entry ID to the index of the Entry in self.entries.
        self._entry_id_to_index_map: dict[int, int] = {}
        # # List of filtered Entry indexes generated by the filter_entries() method.
        # Duplicate Entries
        # Defined by Entries that point to files that one or more other Entries are also pointing to.
        # tuple(int, list[int])
        self.dupe_entries: list[tuple[int, list[int]]] = []

        # Collations ===========================================================
        # List of every Collation object.
        self.collations: list[Collation] = []
        self._collation_id_to_index_map: dict[int, int] = {}

        # File Interfacing =====================================================
        self.dir_file_count: int = -1
        self.files_not_in_library: list[str] = []
        self.missing_files: list[str] = []
        self.fixed_files: list[str] = []  # TODO: Get rid of this.
        self.missing_matches: dict = {}
        # Duplicate Files
        # Defined by files that are exact or similar copies to others. Generated by DupeGuru.
        # (Filepath, Matched Filepath, Match Percentage)
        self.dupe_files: list[tuple[str, str, int]] = []
        # Maps the filenames of entries in the Library to their entry's index in the self.entries list.
        #   Used for O(1) lookup of a file based on the current index (page number - 1) of the image being looked at.
        #   That filename can then be used to provide quick lookup to image metadata entries in the Library.
        # 	NOTE: On Windows, these strings are always lowercase.
        self.filename_to_entry_id_map: dict[str, int] = {}
        # A list of file extensions to be ignored by TagStudio.
        self.default_ext_blacklist: list[str] = ["json", "xmp", "aae"]
        self.ignored_extensions: list[str] = self.default_ext_blacklist

        # Tags =================================================================
        # List of every Tag object (ts-v8).
        self.tags: list[Tag] = []
        # Map of each Tag ID with its entry reference count.
        self._tag_entry_ref_map: dict[int, int] = {}
        self.tag_entry_refs: list[tuple[int, int]] = []
        # Map of every Tag name and alias to the ID(s) of its associated Tag(s).
        #   Used for O(1) lookup of Tag IDs based on search terms.
        #   NOTE: While it is recommended to keep Tag aliases unique to each Tag,
        #   there may be circumstances where this is not possible or elegant.
        #   Because of this, names and aliases are mapped to a list of IDs rather than a
        #   singular ID to handle potential alias collision.
        self._tag_strings_to_id_map: dict[str, list[int]] = {}
        # Map of every Tag ID to an array of Tag IDs that make up the Tag's "cluster", aka a list
        # of references from other Tags that specify this Tag as one of its subtags.
        #   This in effect is like a reverse subtag map.
        #   Used for O(1) lookup of the Tags to return in a query given a Tag ID.
        self._tag_id_to_cluster_map: dict[int, list[int]] = {}
        # Map of every Tag ID to the index of the Tag in self.tags.
        self._tag_id_to_index_map: dict[int, int] = {}

    def create_library(self, path: str | Path) -> bool:
        """Creates an SQLite DB at path.

        Args:
            path (str): Path for database

        Returns:
            bool: True if created, False if error.
        """

        if isinstance(path, str):
            path = Path(path)

        # If '.TagStudio' is the name, raise path by one.
        if ts_core.TS_FOLDER_NAME == path.name:
            path = path.parent

        try:
            self.clear_internal_vars()
            self.root_path = path
            self.verify_ts_folders()

            connection_string = (
                f"sqlite:///{path / ts_core.TS_FOLDER_NAME / ts_core.LIBRARY_FILENAME}"
            )
            self.engine = make_engine(connection_string=connection_string)
            make_tables(engine=self.engine)

            session = Session(self.engine)
            with session.begin():
                session.add_all(library_defaults())

        except Exception as e:
            LOGGER.exception(e)
            return False

        return True

    def verify_ts_folders(self) -> None:
        """Verifies/creates folders required by TagStudio."""

        if self.root_path is None:
            raise ValueError("No path set.")

        full_ts_path = self.root_path / ts_core.TS_FOLDER_NAME
        full_backup_path = full_ts_path / ts_core.BACKUP_FOLDER_NAME
        full_collage_path = full_ts_path / ts_core.COLLAGE_FOLDER_NAME

        for path in [full_ts_path, full_backup_path, full_collage_path]:
            if not path.exists() and not path.is_dir():
                path.mkdir(parents=True, exist_ok=True)

    def verify_default_tags(self, tag_list: list[JsonTag]) -> list[JsonTag]:
        """
        Ensures that the default builtin tags  are present in the Library's
        save file. Takes in and returns the tag dictionary from the JSON file.
        """
        missing: list[JsonTag] = []

        for m in missing:
            tag_list.append(m)

        return tag_list

    def open_library(self, path: str | Path) -> bool:
        """Opens an SQLite DB at path.

        Args:
            path (str): Path for database

        Returns:
            bool: True if exists/opened, False if not.
        """
        if isinstance(path, str):
            path = Path(path)

        # If '.TagStudio' is the name, raise path by one.
        if ts_core.TS_FOLDER_NAME == path.name:
            path = path.parent

        sqlite_path = path / ts_core.LIBRARY_FILENAME

        if sqlite_path.exists() and sqlite_path.is_file():
            connection_string = f"sqlite:///{path / ts_core.LIBRARY_FILENAME}"
            self.engine = make_engine(connection_string=connection_string)
            make_tables(engine=self.engine)
            return True
        else:
            return self.create_library(path=path)

    def clear_internal_vars(self):
        """Clears the internal variables of the Library object."""
        self.root_path = None
        self.is_legacy_library = False

        self._next_entry_id = 0
        # self.filtered_entries.clear()
        self._entry_id_to_index_map.clear()

        self._collation_id_to_index_map.clear()

        self.missing_matches = {}
        self.dir_file_count = -1
        self.files_not_in_library.clear()
        self.missing_files.clear()
        self.fixed_files.clear()
        self.filename_to_entry_id_map = {}
        self.ignored_extensions = self.default_ext_blacklist

        self.tags.clear()
        self._next_tag_id = 1000
        self._tag_strings_to_id_map = {}
        self._tag_id_to_cluster_map = {}
        self._tag_id_to_index_map = {}
        self._tag_entry_ref_map.clear()

    def refresh_dir(self) -> Iterator[int]:
        """Scans a directory for files, and adds those relative filenames to internal variables."""

        if self.root_path is None:
            raise ValueError("No library path set.")

        self.dir_file_count = 0

        print("starting")

        # Scans the directory for files, keeping track of:
        #   - Total file count
        start_time = time.time()
        for path in self.root_path.glob("**/*"):
            str_path = str(path)
            if (
                not path.is_dir()
                and "$RECYCLE.BIN" not in str_path
                and ts_core.TS_FOLDER_NAME not in str_path
                and "tagstudio_thumbs" not in str_path
            ):
                suffix = path.suffix.lower()
                if suffix != "" and suffix[0] == ".":
                    suffix = suffix[1:]

                if suffix not in self.ignored_extensions:
                    self.dir_file_count += 1

                    relative_path = path.relative_to(self.root_path)
                    if not path_in_db(path=relative_path, engine=self.engine):
                        self.add_entry_to_library(entry=Entry(path=relative_path))

            end_time = time.time()
            # Yield output every 1/30 of a second
            if (end_time - start_time) > 0.034:
                yield self.dir_file_count
                start_time = time.time()

        print("Done")

    def refresh_missing_files(self) -> Iterator[int]:
        """Tracks the number of Entries that point to an invalid file path."""
        self.missing_files.clear()

        if self.root_path is None:
            raise ValueError("No library path set.")

        for i, entry in enumerate(self.entries):
            full_path = self.root_path / entry.path
            if not full_path.exists() or not full_path.is_file():
                self.missing_files.append(str(full_path))
            yield i

    def remove_entry(self, entry_id: int) -> None:
        """Removes an Entry from the Library."""

        with Session(self.engine) as session, session.begin():
            entry = session.scalar(select(Entry).where(Entry.id == entry_id))
            if entry is None:
                raise ValueError("")
            session.delete(entry)

    # TODO
    def refresh_dupe_entries(self):
        """
        Refreshes the list of duplicate Entries.
        A duplicate Entry is defined as an Entry pointing to a file that one or more
        other Entries are also pointing to.\n
        `dupe_entries = tuple(int, list[int])`
        """
        pass

    # TODO
    def merge_dupe_entries(self):
        """
        Merges duplicate Entries.
        A duplicate Entry is defined as an Entry pointing to a file that one or more
        other Entries are also pointing to.\n
        `dupe_entries = tuple(int, list[int])`
        """
        pass

    # TODO
    def refresh_dupe_files(self):
        """
        Refreshes the list of duplicate files.
        A duplicate file is defined as an identical or near-identical file as determined
        by a DupeGuru results file.
        """
        pass

    # TODO
    def remove_missing_files(self):
        pass

    # TODO
    def remove_missing_matches(self, fixed_indices: list[int]):
        pass

    # TODO
    def fix_missing_files(self):
        """
        Attempts to repair Entries that point to invalid file paths.
        """

        pass

    # TODO
    def _match_missing_file(self, file: str) -> list[str]:
        """
        Tries to find missing entry files within the library directory.
        Works if files were just moved to different subfolders and don't have duplicate names.
        """

        # self.refresh_missing_files()

        matches = [""]

        return matches

    # TODO
    def count_tag_entry_refs(self) -> None:
        """
        Counts the number of entry references for each tag. Stores results
        in `tag_entry_ref_map`.
        """
        pass

    def add_entry_to_library(self, entry: Entry) -> int:
        with Session(self.engine) as session, session.begin():
            session.add(entry)
            session.flush()
            id = entry.id
        return id

    def get_entry(self, entry_id: int) -> Entry:
        """Returns an Entry object given an Entry ID."""
        with Session(self.engine) as session, session.begin():
            entry = session.scalar(select(Entry).where(Entry.id == entry_id))
            session.expunge(entry)

        if entry is None:
            raise ValueError(f"Entry with id {entry_id} not found.")

        return entry

    def get_collation(self, collation_id: int) -> Collation:
        """Returns a Collation object given an Collation ID."""
        return self.collations[self._collation_id_to_index_map[int(collation_id)]]

    # TODO
    def search_library(
        self,
        query: str | None = None,
        entries: bool = True,
        collations: bool = True,
        tag_groups: bool = True,
    ) -> list[tuple[ItemType, int, Path]]:
        """
        Uses a search query to generate a filtered results list.
        Returns a list of (str, int) tuples consisting of a result type and ID.
        """
        if not hasattr(self, "engine"):
            return []

        results: list[tuple[ItemType, int, Path]] = []

        for entry in self.entries:
            results.append((ItemType.ENTRY, entry.id, entry.path))

        return results

    # TODO
    def search_tags(
        self,
        query: str,
        include_cluster: bool = False,
        ignore_builtin: bool = False,
        threshold: int = 1,
        context: list[str] | None = None,
    ) -> list[int]:
        """Returns a list of Tag IDs returned from a string query."""

        return [0, 1]

    def get_all_child_tag_ids(self, tag_id: int) -> list[int]:
        """Recursively traverse a Tag's subtags and return a list of all children tags."""

        all_subtags: set[int] = set([tag_id])

        with Session(self.engine) as session, session.begin():
            tag = session.scalar(select(Tag).where(Tag.id == tag_id))
            if tag is None:
                raise ValueError(f"No tag found with id {tag_id}.")

            subtag_ids = tag.subtag_ids

        all_subtags.update(subtag_ids)

        for sub_id in subtag_ids:
            all_subtags.update(self.get_all_child_tag_ids(sub_id))

        return list(all_subtags)

    # TODO
    def filter_field_templates(self, query: str) -> list[int]:
        """Returns a list of Field Template IDs returned from a string query."""

        matches: list[int] = []

        return matches

    def update_tag(self, tag: Tag) -> None:
        """
        Edits a Tag in the Library.
        This function undoes and redos the following parts of the 'add_tag_to_library()' process:\n
        - Un-maps the old Tag name, shorthand, and aliases from the Tag ID
        and re-maps the new strings to its ID via '_map_tag_names_to_tag_id()'.\n
        - Un
        """

    def remove_tag(self, tag_id: int) -> None:
        """
        Removes a Tag from the Library.
        Disconnects it from all internal lists and maps, then remaps others as needed.
        """
        tag = self.get_tag(tag_id)

        # Step [1/7]:
        # Remove from Entries.
        for e in self.entries:
            if e.fields:
                for f in e.fields:
                    if self.get_field_attr(f, "type") == "tag_box":
                        if tag_id in self.get_field_attr(f, "content"):
                            self.get_field_attr(f, "content").remove(tag.id)

        # Step [2/7]:
        # Remove from Subtags.
        for t in self.tags:
            if t.subtag_ids:
                if tag_id in t.subtag_ids:
                    t.subtag_ids.remove(tag.id)

        # Step [3/7]:
        # Remove ID -> cluster reference.
        if tag_id in self._tag_id_to_cluster_map:
            del self._tag_id_to_cluster_map[tag.id]
        # Remove mentions of this ID in all clusters.
        for key, values in self._tag_id_to_cluster_map.items():
            if tag_id in values:
                values.remove(tag.id)

        # Step [4/7]:
        # Remove mapping of this ID to its index in the tags list.
        if tag.id in self._tag_id_to_index_map:
            del self._tag_id_to_index_map[tag.id]

        # Step [5/7]:
        # Remove this Tag from the tags list.
        self.tags.remove(tag)

        # Step [6/7]:
        # Remap the other Tag IDs to their new indices in the tags list.
        self._tag_id_to_index_map.clear()
        for i, t in enumerate(self.tags):
            self._map_tag_id_to_index(t, i)

        # Step [7/7]:
        # Remap all existing Tag names.
        self._tag_strings_to_id_map.clear()
        for t in self.tags:
            self._map_tag_strings_to_tag_id(t)

    def get_tag_ref_count(self, tag_id: int) -> tuple[int, int]:
        """Returns an int tuple (entry_ref_count, subtag_ref_count) of Tag reference counts."""
        entry_ref_count: int = 0
        subtag_ref_count: int = 0

        for e in self.entries:
            if e.fields:
                for f in e.fields:
                    if self.get_field_attr(f, "type") == "tag_box":
                        if tag_id in self.get_field_attr(f, "content"):
                            entry_ref_count += 1
                            break

        for t in self.tags:
            if t.subtag_ids:
                if tag_id in t.subtag_ids:
                    subtag_ref_count += 1

        # input()
        return (entry_ref_count, subtag_ref_count)

    def update_entry_path(self, entry_id: int, path: str) -> None:
        """Updates an Entry's path."""
        self.get_entry(entry_id).path = path

    def update_entry_filename(self, entry_id: int, filename: str) -> None:
        """Updates an Entry's filename."""
        self.get_entry(entry_id).filename = filename

    def update_entry_field(self, entry_id: int, field_index: int, content, mode: str):
        """Updates an Entry's specific field. Modes: append, remove, replace."""

        field_id: int = list(self.get_entry(entry_id).fields[field_index].keys())[0]
        if mode.lower() == "append" or mode.lower() == "extend":
            for i in content:
                if i not in self.get_entry(entry_id).fields[field_index][field_id]:
                    self.get_entry(entry_id).fields[field_index][field_id].append(i)
        elif mode.lower() == "replace":
            self.get_entry(entry_id).fields[field_index][field_id] = content
        elif mode.lower() == "remove":
            for i in content:
                self.get_entry(entry_id).fields[field_index][field_id].remove(i)

    def does_field_content_exist(self, entry_id: int, field_id: int, content) -> bool:
        """Returns whether or not content exists in a specific entry field type."""
        # entry = self.entries[entry_index]
        entry = self.get_entry(entry_id)
        indices = self.get_field_index_in_entry(entry, field_id)
        for i in indices:
            if self.get_field_attr(entry.fields[i], "content") == content:
                return True
        return False

    def add_generic_data_to_entry(self, data, entry_id: int):
        """Adds generic data to an Entry on a "best guess" basis. Used in adding scraped data."""
        if data:
            # Add a Title Field if the data doesn't already exist.
            if data.get("title"):
                field_id = 0  # Title Field ID
                if not self.does_field_content_exist(entry_id, field_id, data["title"]):
                    self.add_field_to_entry(entry_id, field_id)
                    self.update_entry_field(entry_id, -1, data["title"], "replace")

            # Add an Author Field if the data doesn't already exist.
            if data.get("author"):
                field_id = 1  # Author Field ID
                if not self.does_field_content_exist(
                    entry_id, field_id, data["author"]
                ):
                    self.add_field_to_entry(entry_id, field_id)
                    self.update_entry_field(entry_id, -1, data["author"], "replace")

            # Add an Artist Field if the data doesn't already exist.
            if data.get("artist"):
                field_id = 2  # Artist Field ID
                if not self.does_field_content_exist(
                    entry_id, field_id, data["artist"]
                ):
                    self.add_field_to_entry(entry_id, field_id)
                    self.update_entry_field(entry_id, -1, data["artist"], "replace")

            # Add a Date Published Field if the data doesn't already exist.
            if data.get("date_published"):
                field_id = 14  # Date Published Field ID
                date = str(
                    datetime.datetime.strptime(
                        data["date_published"], "%Y-%m-%d %H:%M:%S"
                    )
                )
                if not self.does_field_content_exist(entry_id, field_id, date):
                    self.add_field_to_entry(entry_id, field_id)
                    # entry = self.entries[entry_id]
                    self.update_entry_field(entry_id, -1, date, "replace")

            # Process String Tags if the data doesn't already exist.
            if data.get("tags"):
                tags_field_id = 6  # Tags Field ID
                content_tags_field_id = 7  # Content Tags Field ID
                meta_tags_field_id = 8  # Meta Tags Field ID
                notes_field_id = 5  # Notes Field ID
                tags: list[str] = data["tags"]
                # extra: list[str] = []
                # for tag in tags:
                # 	if len(tag.split(' ')) > 1:
                # 		extra += tag.split(' ')
                # 	if len(tag.split('_')) > 1:
                # 		extra += tag.split('_')
                # 	if len(tag.split('-')) > 1:
                # 		extra += tag.split('-')
                # tags = tags + extra
                # tags = list(set(tags))
                extra: list[str] = []
                for tag in tags:
                    if len(tag.split("_(")) > 1:
                        extra += tag.replace(")", "").split("_(")
                tags += extra
                tags = list(set(tags))
                tags.sort()

                while "" in tags:
                    tags.remove("")

                # # If the tags were a single string (space delimitated), split them into a list.
                # if isinstance(data["tags"], str):
                # 	tags.clear()
                # 	tags = data["tags"].split(' ')

                # Try to add matching tags in library.
                for tag in tags:
                    matching: list[int] = self.search_tags(
                        tag.replace("_", " ").replace("-", " "),
                        include_cluster=False,
                        ignore_builtin=True,
                        threshold=2,
                        context=tags,
                    )
                    priority_field_index = -1
                    if matching:
                        # NOTE: The following commented-out code enables the ability
                        # to prefer an existing built-in tag_box field to add to
                        # rather than preferring or creating a 'Content Tags' felid.
                        # In my experience, this feature isn't actually what I want,
                        # but the idea behind it isn't bad. Maybe this could be
                        # user configurable and scale with custom fields.

                        # tag_field_indices = self.get_field_index_in_entry(
                        # 	entry_index, tags_field_id)
                        content_tags_field_indices = self.get_field_index_in_entry(
                            self.get_entry(entry_id), content_tags_field_id
                        )
                        # meta_tags_field_indices = self.get_field_index_in_entry(
                        # 	entry_index, meta_tags_field_id)

                        if content_tags_field_indices:
                            priority_field_index = content_tags_field_indices[0]
                        # elif tag_field_indices:
                        # 	priority_field_index = tag_field_indices[0]
                        # elif meta_tags_field_indices:
                        # 	priority_field_index = meta_tags_field_indices[0]

                        if priority_field_index > 0:
                            self.update_entry_field(
                                entry_id, priority_field_index, [matching[0]], "append"
                            )
                        else:
                            self.add_field_to_entry(entry_id, content_tags_field_id)
                            self.update_entry_field(
                                entry_id, -1, [matching[0]], "append"
                            )

                # Add all original string tags as a note.
                str_tags = f"Original Tags: {tags}"
                if not self.does_field_content_exist(
                    entry_id, notes_field_id, str_tags
                ):
                    self.add_field_to_entry(entry_id, notes_field_id)
                    self.update_entry_field(entry_id, -1, str_tags, "replace")

            # Add a Description Field if the data doesn't already exist.
            if "description" in data.keys() and data["description"]:
                field_id = 4  # Description Field ID
                if not self.does_field_content_exist(
                    entry_id, field_id, data["description"]
                ):
                    self.add_field_to_entry(entry_id, field_id)
                    self.update_entry_field(
                        entry_id, -1, data["description"], "replace"
                    )
            if "content" in data.keys() and data["content"]:
                field_id = 4  # Description Field ID
                if not self.does_field_content_exist(
                    entry_id, field_id, data["content"]
                ):
                    self.add_field_to_entry(entry_id, field_id)
                    self.update_entry_field(entry_id, -1, data["content"], "replace")
            if "source" in data.keys() and data["source"]:
                field_id = 21  # Source Field ID
                for source in data["source"].split(" "):
                    if source and source != " ":
                        source = strip_web_protocol(string=source)
                        if not self.does_field_content_exist(
                            entry_id, field_id, source
                        ):
                            self.add_field_to_entry(entry_id, field_id)
                            self.update_entry_field(entry_id, -1, source, "replace")

    def add_field_to_entry(self, entry_id: int, field_id: int) -> None:
        """Adds an empty Field, specified by Field ID, to an Entry via its index."""
        # entry = self.entries[entry_index]
        entry = self.get_entry(entry_id)
        field_type = self.get_field_obj(field_id)["type"]
        if field_type in ts_core.TEXT_FIELDS:
            entry.fields.append({int(field_id): ""})
        elif field_type == "tag_box":
            entry.fields.append({int(field_id): []})
        elif field_type == "datetime":
            entry.fields.append({int(field_id): ""})
        else:
            logging.info(
                f"[LIBRARY][ERROR]: Unknown field id attempted to be added to entry: {field_id}"
            )

    def mirror_entry_fields(self, entry_ids: list[int]) -> None:
        """Combines and mirrors all fields across a list of given Entry IDs."""

        all_fields: list = []
        all_ids: list = []  # Parallel to all_fields
        # Extract and merge all fields from all given Entries.
        for id in entry_ids:
            if id:
                entry = self.get_entry(id)
                if entry and entry.fields:
                    for field in entry.fields:
                        # First checks if their are matching tag_boxes to append to
                        if (
                            self.get_field_attr(field, "type") == "tag_box"
                            and self.get_field_attr(field, "id") in all_ids
                        ):
                            content = self.get_field_attr(field, "content")
                            for i in content:
                                id = int(self.get_field_attr(field, "id"))
                                field_index = all_ids.index(id)
                                if i not in all_fields[field_index][id]:
                                    all_fields[field_index][id].append(i)
                        # If not, go ahead and whichever new field.
                        elif field not in all_fields:
                            all_fields.append(field)
                            all_ids.append(int(self.get_field_attr(field, "id")))

        # Replace each Entry's fields with the new merged ones.
        for id in entry_ids:
            entry = self.get_entry(id)
            if entry:
                entry.fields = all_fields

                # TODO: Replace this and any in CLI with a proper user-defined
                # field storing method.
                order: list[int] = (
                    [0]
                    + [1, 2]
                    + [9, 17, 18, 19, 20]
                    + [10, 14, 11, 12, 13, 22]
                    + [4, 5]
                    + [8, 7, 6]
                    + [3, 21]
                )

                # NOTE: This code is copied from the sort_fields() method.
                entry.fields = sorted(
                    entry.fields,
                    key=lambda x: order.index(self.get_field_attr(x, "id")),
                )

    # def move_entry_field(self, entry_index, old_index, new_index) -> None:
    # 	"""Moves a field in entry[entry_index] from position entry.fields[old_index] to entry.fields[new_index]"""
    # 	entry = self.entries[entry_index]
    # 	pass
    # 	# TODO: Implement.

    def get_field_attr(self, entry_field: dict, attribute: str):
        """Returns the value of a specified attribute inside an Entry field."""
        if attribute.lower() == "id":
            return list(entry_field.keys())[0]
        elif attribute.lower() == "content":
            return entry_field[self.get_field_attr(entry_field, "id")]
        else:
            return self.get_field_obj(self.get_field_attr(entry_field, "id"))[
                attribute.lower()
            ]

    def get_field_obj(self, field_id: int) -> dict:
        """
        Returns a field template object associated with a field ID.
        The objects have "id", "name", and "type" fields.
        """
        if int(field_id) < len(self.default_fields):
            return self.default_fields[int(field_id)]
        else:
            return {"id": -1, "name": "Unknown Field", "type": "unknown"}

    def get_field_index_in_entry(self, entry: Entry, field_id: int) -> list[int]:
        """
        Returns matched indices for the field type in an entry.\n
        Returns an empty list of no field of that type is found in the entry.
        """
        matched = []
        # entry: Entry = self.entries[entry_index]
        # entry = self.get_entry(entry_id)
        if entry.fields:
            for i, field in enumerate(entry.fields):
                if self.get_field_attr(field, "id") == int(field_id):
                    matched.append(i)

        return matched

    def _map_tag_strings_to_tag_id(self, tag: Tag) -> None:
        """
        Maps a Tag's name, shorthand, and aliases to their ID's (in the form of a list).\n
        ⚠️DO NOT USE FOR CONFIDENT DATA REFERENCES!⚠️\n
        This is intended to be used for quick search queries.\n
        Uses name_and_alias_to_tag_id_map.
        """
        # tag_id: int, tag_name: str, tag_aliases: list[str] = []
        name: str = strip_punctuation(tag.name).lower()
        if name not in self._tag_strings_to_id_map:
            self._tag_strings_to_id_map[name] = []
        self._tag_strings_to_id_map[name].append(tag.id)

        shorthand: str = strip_punctuation(tag.shorthand).lower()
        if shorthand not in self._tag_strings_to_id_map:
            self._tag_strings_to_id_map[shorthand] = []
        self._tag_strings_to_id_map[shorthand].append(tag.id)

        for alias in tag.aliases:
            alias = strip_punctuation(alias).lower()
            if alias not in self._tag_strings_to_id_map:
                self._tag_strings_to_id_map[alias] = []
            self._tag_strings_to_id_map[alias].append(tag.id)
            # print(f'{alias.lower()} -> {tag.id}')

    def _map_tag_id_to_cluster(self, tag: Tag, subtags: list[Tag] = None) -> None:
        """
        Maps a Tag's subtag's ID's back to it's parent Tag's ID (in the form of a list).
        Uses tag_id_to_cluster_map.\n
        EX: Tag: "Johnny Bravo", Subtags: "Cartoon Network (TV)", "Character".\n
        Maps "Cartoon Network" -> Johnny Bravo, "Character" -> "Johnny Bravo", and "TV" -> Johnny Bravo."
        """
        # If a list of subtags is not provided, the method will revert to a level 1-depth
        # mapping based on the given Tag's own subtags.
        if not subtags:
            subtags = [self.get_tag(sub_id) for sub_id in tag.subtag_ids]
        for subtag in subtags:
            if subtag.id not in self._tag_id_to_cluster_map.keys():
                self._tag_id_to_cluster_map[subtag.id] = []
            # Stops circular references
            if tag.id not in self._tag_id_to_cluster_map[subtag.id]:
                self._tag_id_to_cluster_map[subtag.id].append(tag.id)
                # If the subtag has subtags of it own, recursively link those to the original Tag.
                if subtag.subtag_ids:
                    self._map_tag_id_to_cluster(
                        tag,
                        [
                            self.get_tag(sub_id)
                            for sub_id in subtag.subtag_ids
                            if sub_id != tag.id
                        ],
                    )

    def _map_tag_id_to_index(self, tag: Tag, index: int) -> None:
        """
        Maps a Tag's ID to the Tag's Index in self.tags.
        Uses _tag_id_to_index_map.
        """
        # self._tag_id_to_index_map[tag.id_] = self.tags.index(tag)
        if index < 0:
            index = len(self.tags) + index
        self._tag_id_to_index_map[tag.id] = index
        # print(f'{tag.id} - {self._tag_id_to_index_map[tag.id]}')

    def _map_entry_id_to_index(self, entry: Entry, index: int) -> None:
        """
        Maps an Entry's ID to the Entry's Index in self.entries.
        Uses _entry_id_to_index_map.
        """
        # if index != None:
        if index < 0:
            index = len(self.entries) + index
        self._entry_id_to_index_map[entry.id] = index
        # else:
        # 	self._entry_id_to_index_map[entry.id_] = self.entries.index(entry)

    def _map_collation_id_to_index(self, collation: Collation, index: int) -> None:
        """
        Maps a Collation's ID to the Collation's Index in self.collations.
        Uses _entry_id_to_index_map.
        """
        # if index != None:
        if index < 0:
            index = len(self.collations) + index
        self._collation_id_to_index_map[collation.id] = index

    def add_tag_to_library(self, tag: Tag) -> int:
        """
        Adds a Tag to the Library. ⚠️Only use at runtime! (Cannot reference tags that are not loaded yet)⚠️\n
        For adding Tags from the Library save file, append Tags to the Tags list
        and then map them using map_library_tags().
        """
        tag.subtag_ids = [x for x in tag.subtag_ids if x != tag.id]
        tag.id = self._next_tag_id
        self._next_tag_id += 1

        self._map_tag_strings_to_tag_id(tag)
        self.tags.append(tag)  # Must be appended before mapping the index!
        self._map_tag_id_to_index(tag, -1)
        self._map_tag_id_to_cluster(tag)

        return tag.id

    def get_tag(self, tag_id: int) -> Tag:
        """Returns a Tag object given a Tag ID."""
        return self.tags[self._tag_id_to_index_map[int(tag_id)]]

    def get_tag_cluster(self, tag_id: int) -> list[int]:
        """Returns a list of Tag IDs that reference this Tag."""
        if tag_id in self._tag_id_to_cluster_map:
            return self._tag_id_to_cluster_map[int(tag_id)]
        return []

    def sort_fields(self, entry_id: int, order: list[int]) -> None:
        """Sorts an Entry's Fields given an ordered list of Field IDs."""
        entry = self.get_entry(entry_id)
        entry.fields = sorted(
            entry.fields, key=lambda x: order.index(self.get_field_attr(x, "id"))
        )
