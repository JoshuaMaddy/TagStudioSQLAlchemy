# Copyright (C) 2024 Travis Abendshien (CyanVoxel).
# Licensed under the GPL-3.0 License.
# Created for TagStudio: https://github.com/CyanVoxel/TagStudio

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from src.alt_core.library import Library
from src.database.table_declarations.tag import Tag, TagInfo
from src.qt.modals.build_tag import BuildTagPanel
from src.qt.widgets.panel import PanelModal, PanelWidget
from src.qt.widgets.tag import TagWidget


class TagDatabasePanel(PanelWidget):
    tag_chosen = Signal(int)

    def __init__(self, library: Library):
        super().__init__()
        self.lib: Library = library
        self.first_tag_id = -1
        self.tag_limit = 30

        self.setMinimumSize(300, 400)
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(6, 0, 6, 0)

        self.search_field = QLineEdit()
        self.search_field.setObjectName("searchField")
        self.search_field.setMinimumSize(QSize(0, 32))
        self.search_field.setPlaceholderText("Search Tags")
        self.search_field.textEdited.connect(
            lambda x=self.search_field.text(): self.update_tags(x)
        )
        self.search_field.returnPressed.connect(
            lambda checked=False: self.on_return(self.search_field.text())
        )

        self.scroll_contents = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_contents)
        self.scroll_layout.setContentsMargins(6, 0, 6, 0)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area = QScrollArea()
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn
        )
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShadow(QFrame.Shadow.Plain)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidget(self.scroll_contents)

        self.root_layout.addWidget(self.search_field)
        self.root_layout.addWidget(self.scroll_area)
        self.update_tags("")

    def on_return(self, text: str):
        if text and self.first_tag_id >= 0:
            # callback(self.first_tag_id)
            self.search_field.setText("")
            self.update_tags("")
        else:
            self.search_field.setFocus()
            self.parentWidget().hide()

    def update_tags(self, query: str):
        # TODO: Look at recycling rather than deleting and reinitializing
        while self.scroll_layout.itemAt(0):
            self.scroll_layout.takeAt(0).widget().deleteLater()

        # If there is a query, get a list of tag_ids that match, otherwise return all
        if query:
            tags = self.lib.search_tags(query, include_cluster=True)[
                : self.tag_limit - 1
            ]
        else:
            # Get tag ids to keep this behaviorally identical
            tags = self.lib.tags

        first_id_set = False

        for tag in tags:
            if not first_id_set:
                self.first_tag_id = tag.id
                first_id_set = True

            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(3)
            tag_widget = TagWidget(
                library=self.lib,
                tag=tag,
                has_edit=True,
                has_remove=False,
            )
            tag_widget.on_edit.connect(
                lambda checked=False, tag=tag: (self.edit_tag(tag))
            )
            row.addWidget(tag_widget)
            self.scroll_layout.addWidget(container)

        self.search_field.setFocus()

    def edit_tag(self, tag: Tag):
        build_tag_panel = BuildTagPanel(library=self.lib, tag=tag)

        self.edit_modal = PanelModal(
            widget=build_tag_panel,
            title=self.lib.get_tag_display_name(tag=tag),
            window_title="Edit Tag",
            done_callback=(self.update_tags(query=self.search_field.text())),
            has_save=True,
        )

        self.edit_modal.saved.connect(
            lambda: self.edit_tag_callback(build_tag_panel.build_tag())
        )
        self.edit_modal.show()

    def edit_tag_callback(self, tag_info: TagInfo):
        self.lib.update_tag(tag_info=tag_info)
        self.update_tags(self.search_field.text())
