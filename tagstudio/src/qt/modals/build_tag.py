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
from src.alt_core.library import Library, Tag  # type: ignore
from src.core.palette import ColorType, get_tag_color  # type: ignore
from src.database import queries  # type: ignore
from src.database.table_declarations.tag import TagColor, TagInfo  # type: ignore
from src.qt.modals.tag_search import TagSearchPanel  # type: ignore
from src.qt.widgets.panel import PanelModal, PanelWidget  # type: ignore
from src.qt.widgets.tag import TagWidget  # type: ignore

ERROR = "[ERROR]"
WARNING = "[WARNING]"
INFO = "[INFO]"

logging.basicConfig(format="%(message)s", level=logging.INFO)


class BuildTagPanel(PanelWidget):
    on_edit = Signal(Tag)

    def __init__(self, library: Library, tag: Tag | None = None):
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

        # Data
        self.subtag_ids: set[int] = set()
        self.tag = tag
        self.__set_tag()

    def set_styles(self, color: str) -> None:
        self.color_field.setStyleSheet(
            f"""combobox-popup:0;
            font-weight:600;
            color:{get_tag_color(ColorType.TEXT, color.lower())}; 
            background-color:{get_tag_color(ColorType.PRIMARY, color.lower())};
            """
        )

    def add_subtag_callback(self, tag_id: int):
        self.subtag_ids.add(tag_id)
        self.set_subtag_widget()

    def remove_subtag_callback(self, tag_id: int):
        self.subtag_ids.remove(tag_id)
        self.set_subtag_widget()

    def set_subtag_widget(self):
        # Clear entries
        while self.scroll_layout.itemAt(0):
            self.scroll_layout.takeAt(0).widget().deleteLater()

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        for tag_id in self.subtag_ids:
            tag_widget = TagWidget(
                library=self.lib,
                tag=self.lib.get_tag(tag=tag_id),
                has_edit=False,
                has_remove=True,
            )
            tag_widget.on_remove.connect(
                lambda tag_id=tag_id: self.remove_subtag_callback(tag_id=tag_id)
            )
            layout.addWidget(tag_widget)

        self.scroll_layout.addWidget(widget)

    def __set_tag(self):
        if self.tag is None:
            tag = Tag(name="New Tag")
            self.tag = tag
            self.name_field.setText(self.tag.name)
            self.shorthand_field.setText(self.tag.shorthand or "")
            self.aliases_field.setText("\n".join(self.tag.alias_strings))
            # TODO FIX
            self.color_field.setCurrentIndex(0)

        else:
            with self.lib.closing_database_session() as session:
                tag_ = queries.get_tag(tag=self.tag.id, session=session)

                self.name_field.setText(tag_.name)
                self.shorthand_field.setText(tag_.shorthand or "")
                self.aliases_field.setText("\n".join(tag_.alias_strings))
                self.subtag_ids.update(tag_.subtag_ids)
                # TODO FIX
                self.color_field.setCurrentIndex(0)

        self.set_subtag_widget()

    def build_tag(self) -> TagInfo:
        aliases = set(self.aliases_field.toPlainText().split("\n"))

        tag_color_name = self.color_field.currentText().lower() or "default"
        tag_color_name = tag_color_name.replace(" ", "_")

        tag_info = TagInfo(
            id=self.tag.id if self.tag else None,
            name=self.name_field.text(),
            aliases=aliases,
            shorthand=self.shorthand_field.text() or None,
            subtag_ids=set(self.subtag_ids),
            color=TagColor[tag_color_name],
        )

        logging.info(f"Built {tag_info}")

        return tag_info
