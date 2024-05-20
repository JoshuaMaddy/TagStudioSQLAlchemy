# Copyright (C) 2024 Travis Abendshien (CyanVoxel).
# Licensed under the GPL-3.0 License.
# Created for TagStudio: https://github.com/CyanVoxel/TagStudio


import logging
import math

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from src.alt_core.library import Library
from src.core.palette import ColorType, get_tag_color
from src.qt.widgets.panel import PanelWidget
from src.qt.widgets.tag import TagWidget

ERROR = "[ERROR]"
WARNING = "[WARNING]"
INFO = "[INFO]"

logging.basicConfig(format="%(message)s", level=logging.INFO)


class TagSearchPanel(PanelWidget):
    tag_chosen = Signal(int)

    def __init__(self, library: Library):
        super().__init__()
        self.lib: Library = library
        self.first_tag_id = None
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

    def on_return(self, text: str):
        if text and self.first_tag_id is not None:
            self.tag_chosen.emit(self.first_tag_id)
            self.search_field.setText("")
            self.update_tags()
        else:
            self.search_field.setFocus()
            self.parentWidget().hide()

    def update_tags(self, query: str = ""):
        while self.scroll_layout.count():
            self.scroll_layout.takeAt(0).widget().deleteLater()

        # TODO
        found_tags = self.lib.search_tags(query)

        for tag in found_tags:
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(3)
            tag_widget = TagWidget(
                library=self.lib,
                tag=self.lib.get_tag(tag=tag.id, with_subtags=True),
                has_edit=False,
                has_remove=False,
            )
            button = QPushButton()
            button.setMinimumSize(23, 23)
            button.setMaximumSize(23, 23)
            button.setText("+")
            button.setStyleSheet(
                f"QPushButton{{"
                f"background: {get_tag_color(ColorType.PRIMARY, tag.color)};"
                f"color: {get_tag_color(ColorType.TEXT, tag.color)};"
                f"font-weight: 600;"
                f"border-color:{get_tag_color(ColorType.BORDER, tag.color)};"
                f"border-radius: 6px;"
                f"border-style:solid;"
                f"border-width: {math.ceil(1*self.devicePixelRatio())}px;"
                f"padding-bottom: 5px;"
                f"font-size: 20px;"
                f"}}"
                f"QPushButton::hover"
                f"{{"
                f"border-color:{get_tag_color(ColorType.LIGHT_ACCENT, tag.color)};"
                f"color: {get_tag_color(ColorType.DARK_ACCENT, tag.color)};"
                f"background: {get_tag_color(ColorType.LIGHT_ACCENT, tag.color)};"
                f"}}"
            )

            button.clicked.connect(
                lambda checked=False, tag_id=tag.id: self.tag_chosen.emit(tag_id)
            )

            layout.addWidget(tag_widget)
            layout.addWidget(button)

            self.scroll_layout.addWidget(widget)

        self.search_field.setFocus()
