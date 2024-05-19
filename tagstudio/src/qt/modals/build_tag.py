# Copyright (C) 2024 Travis Abendshien (CyanVoxel).
# Licensed under the GPL-3.0 License.
# Created for TagStudio: https://github.com/CyanVoxel/TagStudio


import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import Session
from src.alt_core.library import Library, Tag, TagAlias  # type: ignore
from src.core.palette import ColorType, get_tag_color  # type: ignore
from src.database.queries import get_objects_by_ids  # type: ignore
from src.database.table_declarations.tag import TagColor  # type: ignore
from src.qt.modals.tag_search import TagSearchPanel  # type: ignore
from src.qt.widgets.panel import PanelModal, PanelWidget  # type: ignore
from src.qt.widgets.tag import TagWidget  # type: ignore

ERROR = "[ERROR]"
WARNING = "[WARNING]"
INFO = "[INFO]"

logging.basicConfig(format="%(message)s", level=logging.INFO)


class BuildTagPanel(PanelWidget):
    on_edit = Signal(Tag)

    def __init__(self, library: Library, tag_id: int = -1):
        super().__init__()
        self.lib: Library = library
        self.setMinimumSize(300, 400)
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(6, 0, 6, 0)
        self.root_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Name -----------------------------------------------------------------
        self.name_widget = QWidget()
        self.name_layout = QVBoxLayout(self.name_widget)
        self.name_layout.setStretch(1, 1)
        self.name_layout.setContentsMargins(0, 0, 0, 0)
        self.name_layout.setSpacing(0)
        self.name_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.name_title = QLabel()
        self.name_title.setText("Name")
        self.name_layout.addWidget(self.name_title)
        self.name_field = QLineEdit()
        self.name_layout.addWidget(self.name_field)

        # Shorthand ------------------------------------------------------------
        self.shorthand_widget = QWidget()
        self.shorthand_layout = QVBoxLayout(self.shorthand_widget)
        self.shorthand_layout.setStretch(1, 1)
        self.shorthand_layout.setContentsMargins(0, 0, 0, 0)
        self.shorthand_layout.setSpacing(0)
        self.shorthand_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.shorthand_title = QLabel()
        self.shorthand_title.setText("Shorthand")
        self.shorthand_layout.addWidget(self.shorthand_title)
        self.shorthand_field = QLineEdit()
        self.shorthand_layout.addWidget(self.shorthand_field)

        # Aliases --------------------------------------------------------------
        self.aliases_widget = QWidget()
        self.aliases_layout = QVBoxLayout(self.aliases_widget)
        self.aliases_layout.setStretch(1, 1)
        self.aliases_layout.setContentsMargins(0, 0, 0, 0)
        self.aliases_layout.setSpacing(0)
        self.aliases_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.aliases_title = QLabel()
        self.aliases_title.setText("Aliases")
        self.aliases_layout.addWidget(self.aliases_title)
        self.aliases_field = QTextEdit()
        self.aliases_field.setAcceptRichText(False)
        self.aliases_field.setMinimumHeight(40)
        self.aliases_layout.addWidget(self.aliases_field)

        # Subtags ------------------------------------------------------------
        self.subtags_widget = QWidget()
        self.subtags_layout = QVBoxLayout(self.subtags_widget)
        self.subtags_layout.setStretch(1, 1)
        self.subtags_layout.setContentsMargins(0, 0, 0, 0)
        self.subtags_layout.setSpacing(0)
        self.subtags_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.subtags_title = QLabel()
        self.subtags_title.setText("Subtags")
        self.subtags_layout.addWidget(self.subtags_title)

        self.scroll_contents = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_contents)
        self.scroll_layout.setContentsMargins(6, 0, 6, 0)
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShadow(QFrame.Shadow.Plain)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setWidget(self.scroll_contents)

        self.subtags_layout.addWidget(self.scroll_area)

        self.subtags_add_button = QPushButton()
        self.subtags_add_button.setText("+")
        tsp = TagSearchPanel(self.lib)
        tsp.tag_chosen.connect(lambda x: self.add_subtag_callback(x))  # type: ignore
        self.add_tag_modal = PanelModal(tsp, "Add Subtags", "Add Subtags")
        self.subtags_add_button.clicked.connect(self.add_tag_modal.show)
        self.subtags_layout.addWidget(self.subtags_add_button)

        # Shorthand ------------------------------------------------------------
        self.color_widget = QWidget()
        self.color_layout = QVBoxLayout(self.color_widget)
        self.color_layout.setStretch(1, 1)
        self.color_layout.setContentsMargins(0, 0, 0, 0)
        self.color_layout.setSpacing(0)
        self.color_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.color_title = QLabel()
        self.color_title.setText("Color")
        self.color_layout.addWidget(self.color_title)
        self.color_field = QComboBox()
        self.color_field.setEditable(False)
        self.color_field.setMaxVisibleItems(10)
        self.color_field.setStyleSheet("combobox-popup:0;")

        for color in [tag_color.value for tag_color in TagColor]:
            self.color_field.addItem(color.title())

        self.color_field.currentTextChanged.connect(self.set_styles)
        self.color_layout.addWidget(self.color_field)

        # Add Widgets to Layout ================================================
        self.root_layout.addWidget(self.name_widget)
        self.root_layout.addWidget(self.shorthand_widget)
        self.root_layout.addWidget(self.aliases_widget)
        self.root_layout.addWidget(self.subtags_widget)
        self.root_layout.addWidget(self.color_widget)

        if tag_id >= 0:
            self.tag = self.lib.get_tag(tag_id)
        else:
            self.tag = Tag(name="New Tag")

        self.set_tag(self.tag)

    def set_styles(self, color: str) -> None:
        self.color_field.setStyleSheet(
            f"""combobox-popup:0;
            font-weight:600;
            color:{get_tag_color(ColorType.TEXT, color.lower())}; 
            background-color:{get_tag_color(ColorType.PRIMARY, color.lower())};
            """
        )

    def add_subtag_callback(self, tag_id: int):
        logging.info(f"Adding {tag_id}")
        with Session(self.lib.engine) as session, session.begin():
            self.tag.add_subtag(tag=tag_id, session=session)

        self.set_subtags()

    def remove_subtag_callback(self, tag_id: int):
        logging.info(f"Removing {tag_id}")
        with Session(self.lib.engine) as session, session.begin():
            self.tag.remove_subtag(tag=tag_id, session=session)

        self.set_subtags()

    def set_subtags(self):
        while self.scroll_layout.itemAt(0):
            self.scroll_layout.takeAt(0).widget().deleteLater()

        logging.info(f"Setting {self.tag.subtag_ids}")

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        for tag_id in self.tag.subtag_ids:
            tag_widget = TagWidget(
                library=self.lib,
                tag=self.lib.get_tag(tag_id),
                has_edit=False,
                has_remove=True,
            )
            tag_widget.on_remove.connect(
                lambda tag_id=tag_id: self.remove_subtag_callback(tag_id=tag_id)
            )
            layout.addWidget(tag_widget)

        self.scroll_layout.addWidget(widget)

    def set_tag(self, tag: Tag):
        # tag = self.lib.get_tag(tag_id)
        self.name_field.setText(tag.name)
        self.shorthand_field.setText(tag.shorthand or "")
        self.aliases_field.setText("\n".join(tag.alias_strings))

        self.set_subtags()

        # TODO FIX
        self.color_field.setCurrentIndex(0)

    def build_tag(self) -> Tag:
        aliases = set(
            [
                TagAlias(name=name)
                for name in self.aliases_field.toPlainText().split("\n")
            ]
        )

        subtags: list[Tag] = get_objects_by_ids(
            ids=self.tag.subtag_ids,
            type=Tag,  # type: ignore
            engine=self.lib.engine,
        )

        new_tag: Tag = Tag(
            name=self.name_field.text(),
            aliases=aliases,
            shorthand=self.shorthand_field.text() or None,
            subtags=set(subtags),
            color=TagColor[self.color_field.currentText().lower()],
        )

        logging.info(f"Built {new_tag}")

        return new_tag
