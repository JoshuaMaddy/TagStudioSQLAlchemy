# Copyright (C) 2024 Travis Abendshien (CyanVoxel).
# Licensed under the GPL-3.0 License.
# Created for TagStudio: https://github.com/CyanVoxel/TagStudio


import logging
import math
import typing

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QPushButton
from src.alt_core.library import Library
from src.alt_core.types import EntrySearchResult
from src.database.table_declarations.entry import Entry
from src.database.table_declarations.field import TagBoxField
from src.database.table_declarations.tag import Tag
from src.qt.flowlayout import FlowLayout
from src.qt.modals.build_tag import BuildTagPanel
from src.qt.modals.tag_search import TagSearchPanel
from src.qt.widgets.fields import FieldWidget
from src.qt.widgets.panel import PanelModal
from src.qt.widgets.tag import TagWidget

# Only import for type checking/autocompletion, will not be imported at runtime.
if typing.TYPE_CHECKING:
    from src.qt.ts_qt import QtDriver


class TagBoxWidget(FieldWidget):
    updated = Signal()

    def __init__(
        self,
        field: TagBoxField,
        item: Entry,
        title: str,
        library: Library,
        tags: set[Tag],
        driver: "QtDriver",
    ) -> None:
        super().__init__(title=title, field=field)
        self.item = item
        self.lib = library
        self.driver = driver  # Used for creating tag click callbacks that search entries for that tag.
        self.tags = tags
        self.setObjectName("tagBox")
        self.base_layout = FlowLayout()
        self.base_layout.setGridEfficiency(False)
        self.base_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.base_layout)

        self.add_button = QPushButton()
        self.add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_button.setMinimumSize(23, 23)
        self.add_button.setMaximumSize(23, 23)
        self.add_button.setText("+")
        self.add_button.setStyleSheet(
            f"QPushButton{{"
            f"background: #1e1e1e;"
            f"color: #FFFFFF;"
            f"font-weight: bold;"
            f"border-color: #333333;"
            f"border-radius: 6px;"
            f"border-style:solid;"
            f"border-width:{math.ceil(1*self.devicePixelRatio())}px;"
            f"padding-bottom: 5px;"
            f"font-size: 20px;"
            f"}}"
            f"QPushButton::hover"
            f"{{"
            f"border-color: #CCCCCC;"
            f"background: #555555;"
            f"}}"
        )
        tag_search_panel = TagSearchPanel(self.lib)
        tag_search_panel.tag_chosen.connect(
            lambda tag_id: self.add_tag_callback(tag_id)  # type: ignore
        )
        self.add_modal = PanelModal(tag_search_panel, title, "Add Tags")
        self.add_button.clicked.connect(
            lambda: (tag_search_panel.update_tags(), self.add_modal.show())  # type: ignore
        )

        self.set_tags(tags)

    def set_item(self, item: Entry):
        self.item = item

    def set_tags(self, tags: set[Tag]):
        logging.info(
            f"[TAG BOX] Setting tag box tags:{[tag.name for tag in tags]} for entry:{self.item.id}"
        )

        self.clear_tag_widgets()

        for tag in sorted(tags, key=lambda tag: tag.name):
            tag_widget = TagWidget(
                library=self.lib,
                tag=tag,
                has_edit=True,
                has_remove=True,
            )
            tag_widget.on_click.connect(
                lambda checked=False, query=f"tag_id: {tag.id}": (
                    self.driver.main_window.searchField.setText(query),
                    self.driver.filter_items(query),
                )
            )
            tag_widget.on_remove.connect(
                lambda checked=False, tag=tag: self.remove_tag(tag)
            )
            tag_widget.on_edit.connect(
                lambda checked=False, tag=tag: self.edit_tag(tag)
            )

            self.base_layout.addWidget(tag_widget)

        self.tags = tags

        self.base_layout.addWidget(self.add_button)

        # Handles an edge case where there are no more tags and the '+' button
        # doesn't move all the way to the left.
        if self.base_layout.itemAt(0) and not self.base_layout.itemAt(1):
            self.base_layout.update()

    def edit_tag(self, tag: Tag):
        build_tag_panel = BuildTagPanel(library=self.lib, tag=tag)
        self.edit_modal = PanelModal(
            widget=build_tag_panel,
            title=self.lib.get_tag(tag=tag, with_subtags=True).display_name,
            window_title="Edit Tag",
            done_callback=(self.driver.preview_panel.update_widgets),
            has_save=True,
        )
        self.edit_modal.saved.connect(
            lambda: self.lib.update_tag(build_tag_panel.build_tag())
        )
        self.edit_modal.show()

    def add_tag_callback(self, tag_id: int):
        for selected in self.driver.selected:
            if isinstance(selected, EntrySearchResult):
                entry = self.driver.lib.get_entry_and_fields(selected.id)
                if self.field in entry.tag_box_fields:
                    field_to_edit = entry.tag_box_fields[
                        entry.tag_box_fields.index(self.field)
                    ]

                    self.driver.lib.add_tag_to_field(tag=tag_id, field=field_to_edit)
            else:
                raise NotImplementedError

        self.updated.emit()

        if (
            tag_id == self.driver.lib.archived_tag.id
            or tag_id == self.driver.lib.favorite_tag.id
        ):
            self.driver.update_badges()

    # TODO
    def edit_tag_callback(self, tag: Tag):
        self.lib.update_tag(tag)

    def remove_tag(self, tag: Tag):
        for selected in self.driver.selected:
            if isinstance(selected, EntrySearchResult):
                entry = self.driver.lib.get_entry_and_fields(selected.id)
                if self.field in entry.tag_box_fields:
                    field_to_edit = entry.tag_box_fields[
                        entry.tag_box_fields.index(self.field)
                    ]
                    self.driver.lib.remove_tag_from_field(tag=tag, field=field_to_edit)
            else:
                raise NotImplementedError
            self.updated.emit()

        if tag == self.driver.lib.archived_tag or tag == self.driver.lib.favorite_tag:
            self.driver.update_badges()

    def clear_tag_widgets(self) -> None:
        for i in range(self.base_layout.count()):
            child = self.base_layout.itemAt(i)

            if child:
                widget = child.widget()

                if widget is self.add_button:
                    continue
                else:
                    widget.deleteLater()
