# Copyright (C) 2024 Travis Abendshien (CyanVoxel).
# Licensed under the GPL-3.0 License.
# Created for TagStudio: https://github.com/CyanVoxel/TagStudio

import logging
import os
import time
from typing import TYPE_CHECKING, Any, Callable

import cv2
import rawpy  # type: ignore
from humanfriendly import format_size
from PIL import Image, UnidentifiedImageError
from PIL.Image import DecompressionBombError
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy import select
from src.alt_core.library import Entry, Library
from src.alt_core.types import (
    CollationSearchResult,
    EntrySearchResult,
    SearchResult,
    SettingItems,
    Theme,
)
from src.core.constants import IMAGE_TYPES, RAW_IMAGE_TYPES, VIDEO_TYPES
from src.database.table_declarations.field import (
    Field,
    TagBoxField,
    TextField,
)
from src.qt.helpers.file_opener import FileOpenerHelper, FileOpenerLabel, open_file
from src.qt.modals.add_field import AddFieldModal
from src.qt.widgets.fields import FieldContainer
from src.qt.widgets.panel import PanelModal
from src.qt.widgets.tag_box import TagBoxWidget
from src.qt.widgets.text import TextWidget
from src.qt.widgets.text_line_edit import EditTextLine
from src.qt.widgets.thumb_renderer import ThumbRenderer

# Only import for type checking/autocompletion, will not be imported at runtime.
if TYPE_CHECKING:
    from src.qt.ts_qt import QtDriver

ERROR = "[ERROR]"
WARNING = "[WARNING]"
INFO = "[INFO]"

logging.basicConfig(format="%(message)s", level=logging.INFO)


class PreviewPanel(QWidget):
    """The Preview Panel Widget."""

    tags_updated = Signal()

    def __init__(self, library: Library, driver: "QtDriver"):
        super().__init__()
        self.lib = library
        self.driver: QtDriver = driver
        self.initialized = False
        self.isOpen: bool = False
        self.common_fields: set[Field] = set()
        self.mixed_fields: list[Field] = []
        self.selected: list[SearchResult] = []
        self.tag_callback = None
        self.containers: list[FieldContainer] = []

        self.img_button_size: tuple[int, int] = (266, 266)
        self.image_ratio: float = 1.0

        self.image_container = QWidget()
        image_layout = QHBoxLayout(self.image_container)
        image_layout.setContentsMargins(0, 0, 0, 0)

        self.open_file_action = QAction("Open file", self)
        self.open_explorer_action = QAction("Open file in explorer", self)

        self.preview_img = QPushButton()
        self.preview_img.setMinimumSize(*self.img_button_size)
        self.preview_img.setFlat(True)
        self.preview_img.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)

        self.preview_img.addAction(self.open_file_action)
        self.preview_img.addAction(self.open_explorer_action)

        self.thumb_renderer = ThumbRenderer()
        self.thumb_renderer.updated.connect(
            lambda ts, i, s: (self.preview_img.setIcon(i))  # type: ignore
        )
        self.thumb_renderer.updated_ratio.connect(
            lambda ratio: (  # type: ignore
                self.set_image_ratio(ratio),  # type: ignore
                self.update_image_size(
                    (
                        self.image_container.size().width(),
                        self.image_container.size().height(),
                    ),
                    ratio,  # type: ignore
                ),
            )
        )

        image_layout.addWidget(self.preview_img)
        image_layout.setAlignment(self.preview_img, Qt.AlignmentFlag.AlignCenter)

        self.file_label = FileOpenerLabel("Filename")
        self.file_label.setWordWrap(True)
        self.file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.file_label.setStyleSheet("font-weight: bold; font-size: 12px")

        self.dimensions_label = QLabel("Dimensions")
        self.dimensions_label.setWordWrap(True)

        properties_style = (
            f"background-color:{Theme.COLOR_BG.value};"
            f"font-family:Oxanium;"
            f"font-weight:bold;"
            f"font-size:12px;"
            f"border-radius:6px;"
            f"padding-top: 4px;"
            f"padding-right: 1px;"
            f"padding-bottom: 1px;"
            f"padding-left: 1px;"
        )

        self.dimensions_label.setStyleSheet(properties_style)

        self.scroll_layout = QVBoxLayout()
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_layout.setContentsMargins(6, 1, 6, 6)

        scroll_container: QWidget = QWidget()
        scroll_container.setObjectName("entryScrollContainer")
        scroll_container.setLayout(self.scroll_layout)

        info_section = QWidget()
        info_layout = QVBoxLayout(info_section)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(6)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("entryScrollArea")
        scroll_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShadow(QFrame.Shadow.Plain)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        # NOTE: I would rather have this style applied to the scroll_area
        # background and NOT the scroll container background, so that the
        # rounded corners are maintained when scrolling. I was unable to
        # find the right trick to only select that particular element.
        scroll_area.setStyleSheet(
            "QWidget#entryScrollContainer{"
            f"background: {Theme.COLOR_BG.value};"
            "border-radius:6px;"
            "}"
        )
        scroll_area.setWidget(scroll_container)

        info_layout.addWidget(self.file_label)
        info_layout.addWidget(self.dimensions_label)
        info_layout.addWidget(scroll_area)

        # keep list of rendered libraries to avoid needless re-rendering
        self.render_libs: set[str] = set()
        self.libs_layout = QVBoxLayout()
        self.fill_libs_widget(self.libs_layout)

        self.libs_flow_container: QWidget = QWidget()
        self.libs_flow_container.setObjectName("librariesList")
        self.libs_flow_container.setLayout(self.libs_layout)
        self.libs_flow_container.setSizePolicy(
            QSizePolicy.Preferred,  # type: ignore
            QSizePolicy.Maximum,  # type: ignore
        )

        # set initial visibility based on settings
        if not self.driver.settings.value(
            SettingItems.WINDOW_SHOW_LIBS, True, type=bool
        ):
            self.libs_flow_container.hide()

        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Vertical)
        splitter.setHandleWidth(12)
        splitter.splitterMoved.connect(
            lambda: self.update_image_size(
                (
                    self.image_container.size().width(),
                    self.image_container.size().height(),
                )
            )
        )

        splitter.addWidget(self.image_container)
        splitter.addWidget(info_section)
        splitter.addWidget(self.libs_flow_container)
        splitter.setStretchFactor(1, 2)

        self.afb_container = QWidget()
        self.afb_layout = QVBoxLayout(self.afb_container)
        self.afb_layout.setContentsMargins(0, 12, 0, 0)

        self.add_field_button = QPushButton()
        self.add_field_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_field_button.setMinimumSize(96, 28)
        self.add_field_button.setMaximumSize(96, 28)
        self.add_field_button.setText("Add Field")
        self.afb_layout.addWidget(self.add_field_button)
        self.afm = AddFieldModal(self.lib)
        self.place_add_field_button()
        self.update_image_size(
            (self.image_container.size().width(), self.image_container.size().height())
        )

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(splitter)

    def fill_libs_widget(self, layout: QVBoxLayout):
        settings = self.driver.settings
        settings.beginGroup(SettingItems.LIBS_LIST)
        lib_items: dict[str, tuple[str, str]] = {}
        for item_tstamp in settings.allKeys():
            val: str = settings.value(item_tstamp)  # type: ignore
            cut_val = val
            if len(val) > 45:
                cut_val = f"{val[0:10]} ... {val[-10:]}"
            lib_items[item_tstamp] = (val, cut_val)

        settings.endGroup()

        new_keys = set(lib_items.keys())
        if new_keys == self.render_libs:
            # no need to re-render
            return

        # sort lib_items by the key
        libs_sorted = sorted(lib_items.items(), key=lambda item: item[0], reverse=True)

        self.render_libs = new_keys
        self._fill_libs_widget(libs_sorted, layout)

    def _fill_libs_widget(
        self,
        libraries: list[tuple[str, tuple[str, str]]],
        layout: QVBoxLayout,
    ):
        # remove any potential previous items
        self.clear_layout(layout)

        label = QLabel("Recent Libraries")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        row_layout = QHBoxLayout()
        row_layout.addWidget(label)
        layout.addLayout(row_layout)

        def set_button_style(btn: QPushButton, extras: list[str] | None = None):
            base_style = [
                f"background-color:{Theme.COLOR_BG.value};",
                "border-radius:6px;",
                "text-align: left;",
                "padding-top: 3px;",
                "padding-left: 6px;",
                "padding-bottom: 4px;",
            ]

            full_style_rows = base_style + (extras or [])

            btn.setStyleSheet(
                (
                    "QPushButton{"
                    f"{''.join(full_style_rows)}"
                    "}"
                    f"QPushButton::hover{{background-color:{Theme.COLOR_HOVER.value};}}"
                    f"QPushButton::pressed{{background-color:{Theme.COLOR_PRESSED.value};}}"
                )
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        for item_key, (full_val, cut_val) in libraries:
            button = QPushButton(text=cut_val)
            button.setObjectName(f"path{item_key}")

            def open_library_button_clicked(path: str):
                return lambda: self.driver.open_library(path)

            button.clicked.connect(open_library_button_clicked(full_val))
            set_button_style(button)

            button_remove = QPushButton("➖")
            button_remove.setCursor(Qt.CursorShape.PointingHandCursor)
            button_remove.setFixedWidth(30)
            set_button_style(button_remove)

            def remove_recent_library_clicked(key: str):
                return lambda: (
                    self.driver.remove_recent_library(key),
                    self.fill_libs_widget(self.libs_layout),
                )

            button_remove.clicked.connect(remove_recent_library_clicked(item_key))

            row_layout = QHBoxLayout()
            row_layout.addWidget(button)
            row_layout.addWidget(button_remove)

            layout.addLayout(row_layout)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.update_image_size(
            (self.image_container.size().width(), self.image_container.size().height())
        )
        return super().resizeEvent(event)

    def get_preview_size(self) -> tuple[int, int]:
        return (
            self.image_container.size().width(),
            self.image_container.size().height(),
        )

    def set_image_ratio(self, ratio: float):
        self.image_ratio = ratio

    def update_image_size(self, size: tuple[int, int], ratio: float | None = None):
        if ratio:
            self.set_image_ratio(ratio)

        adj_width: float = size[0]
        adj_height: float = size[1]
        # Landscape
        if self.image_ratio > 1:
            adj_height = size[0] * (1 / self.image_ratio)
        # Portrait
        elif self.image_ratio <= 1:
            adj_width = size[1] * self.image_ratio

        if adj_width > size[0]:
            adj_height = adj_height * (size[0] / adj_width)
            adj_width = size[0]
        elif adj_height > size[1]:
            adj_width = adj_width * (size[1] / adj_height)
            adj_height = size[1]

        adj_size = QSize(int(adj_width), int(adj_height))
        self.img_button_size = (int(adj_width), int(adj_height))
        self.preview_img.setMaximumSize(adj_size)
        self.preview_img.setIconSize(adj_size)

    def place_add_field_button(self):
        self.scroll_layout.addWidget(self.afb_container)
        self.scroll_layout.setAlignment(
            self.afb_container, Qt.AlignmentFlag.AlignHCenter
        )

        try:
            self.afm.done.disconnect()
            self.add_field_button.clicked.disconnect()
        except RuntimeError:
            pass

        self.afm.done.connect(
            lambda field: (self.add_field_to_selected(field), self.update_widgets())  # type: ignore
        )

        self.add_field_button.clicked.connect(self.afm.show)

    def add_field_to_selected(self, field_id: int):
        """Adds an entry field to one or more selected items."""
        added: set[SearchResult] = set()
        for selected in self.selected:
            if isinstance(selected, EntrySearchResult) and selected not in added:
                self.lib.add_field_to_entry(entry_id=selected.id, field_id=field_id)
                added.add(selected)

    def update_widgets(self):
        """
        Renders the panel's widgets with the newest data from the Library.
        """
        logging.info(
            f"[ENTRY PANEL] UPDATE WIDGETS ({[selected.id for selected in self.selected]})"
        )

        self.isOpen = True

        window_title = ""

        self.fill_libs_widget(self.libs_layout)

        # 0 Selected Items
        if not self.driver.selected:
            self.zero_items()

        # 1 Selected Item
        elif len(self.driver.selected) == 1:
            if self.lib.root_path is None:
                raise ValueError

            # 1 Selected Entry
            selected = self.driver.selected[0]
            if isinstance(selected, EntrySearchResult):
                window_title = self.one_item(window_title=window_title)

            # 1 Selected Collation
            elif isinstance(selected, CollationSearchResult):
                pass

            # 1 Selected Tag
            else:
                pass

        # Multiple Selected Items
        elif len(self.driver.selected) > 1:
            self.multiple_items()

        self.initialized = True

        self.setWindowTitle(window_title)
        self.show()

    def set_tags_updated_slot(self, slot: object):
        """
        Replacement for tag_callback.
        """
        try:
            self.tags_updated.disconnect()
        except RuntimeError:
            pass
        logging.info("[UPDATE CONTAINER] Setting tags updated slot")
        self.tags_updated.connect(slot)

    def write_container(self, index: int, field: Field, mixed: bool = False):
        """Updates/Creates data for a FieldContainer."""

        with self.lib.closing_database_session() as session:
            self.scroll_layout.takeAt(self.scroll_layout.count() - 1).widget()

            container: FieldContainer | None = None

            if len(self.containers) < (index + 1):
                container = FieldContainer()
                self.containers.append(container)
                self.scroll_layout.addWidget(container)
            else:
                container = self.containers[index]
            if isinstance(field, TagBoxField):
                container.set_title(field.name)
                container.set_inline(False)
                title = f"{field.name} (Tag Box)"
                if not mixed:
                    item = session.scalars(
                        select(Entry).where(Entry.id == self.selected[0].id)
                    ).one()
                    field = session.scalars(
                        select(TagBoxField).where(TagBoxField.id == field.id)
                    ).one()
                    if type(container.get_inner_widget()) == TagBoxWidget:
                        inner_container: TagBoxWidget = container.get_inner_widget()  # type: ignore
                        inner_container.set_item(item)  # type: ignore
                        inner_container.set_tags(field.tags)  # type: ignore
                        try:
                            inner_container.updated.disconnect()  # type: ignore
                        except RuntimeError:
                            pass
                    else:
                        inner_container = TagBoxWidget(  # type: ignore
                            field=field,
                            item=item,
                            title=title,
                            library=self.lib,
                            tags=field.tags,
                            driver=self.driver,
                        )

                        container.set_inner_widget(inner_container)

                    inner_container.field = field

                    inner_container.updated.connect(  # type: ignore
                        lambda: (
                            self.write_container(index, field),
                            self.tags_updated.emit(),
                        )
                    )

                    # NOTE: Tag Boxes have no Edit Button (But will when you can convert field types)
                    prompt = (
                        f'Are you sure you want to remove this "{field.name}" field?'
                    )
                    callback = lambda: (self.remove_field(field), self.update_widgets())

                    container.set_remove_callback(
                        lambda: self.remove_message_box(
                            prompt=prompt, callback=callback
                        )
                    )

                    container.set_copy_callback(None)
                    container.set_edit_callback(None)
                else:
                    text = "<i>Mixed Data</i>"
                    title = f"{field.name} (Wacky Tag Box)"
                    inner_container = TextWidget(title=title, text=text, field=field)  # type: ignore
                    container.set_inner_widget(inner_container)
                    container.set_copy_callback(None)
                    container.set_edit_callback(None)
                    container.set_remove_callback(None)

                self.tags_updated.emit()
            elif isinstance(field, TextField):
                container.set_title(field.name)
                container.set_inline(False)
                if not mixed:
                    text = field.value or ""
                    text = text.replace("\r", "\n")
                else:
                    text = "<i>Mixed Data</i>"

                title = f"{field.name} (Text Line)"
                inner_container: TextWidget = TextWidget(
                    title=title, text=text, field=field
                )
                container.set_inner_widget(inner_container)

                if not mixed:
                    modal = PanelModal(
                        widget=EditTextLine(field.value or ""),
                        title=title,
                        window_title=f"Edit {field.name}",
                        save_callback=(
                            lambda content: (  # type: ignore
                                self.update_field(field, content),  # type: ignore
                                self.update_widgets(),
                            )
                        ),
                    )
                    container.set_edit_callback(modal.show)
                    prompt = (
                        f'Are you sure you want to remove this "{field.name}" field?'
                    )
                    callback = lambda: (self.remove_field(field), self.update_widgets())
                    container.set_remove_callback(
                        lambda: self.remove_message_box(
                            prompt=prompt, callback=callback
                        )
                    )
                    container.set_copy_callback(None)
                else:
                    container.set_edit_callback(None)
                    container.set_copy_callback(None)
                    container.set_remove_callback(None)

            container.edit_button.setHidden(True)
            container.setHidden(False)
            self.place_add_field_button()

    def remove_field(self, field: Field) -> None:
        # TODO only on one, not all
        """Removes a field from all selected Entries, given a field object."""
        selected_entry_ids = [
            selected.id
            for selected in self.selected
            if isinstance(selected, EntrySearchResult)
        ]
        self.lib.remove_field(field=field, entry_ids=selected_entry_ids)

    def update_field(self, field: Field, content: str) -> None:
        # TODO only on one, not all
        """Removes a field from all selected Entries, given a field object."""
        selected_entry_ids = [
            selected.id
            for selected in self.selected
            if isinstance(selected, EntrySearchResult)
        ]
        self.lib.update_field(
            field=field,
            content=content,
            entry_ids=selected_entry_ids,
            mode="replace",
        )

    def remove_message_box(
        self,
        prompt: str,
        callback: Callable[[], Any],
    ) -> None:
        remove_mb = QMessageBox()
        remove_mb.setText(prompt)
        remove_mb.setWindowTitle("Remove Field")
        remove_mb.setIcon(QMessageBox.Icon.Warning)
        cancel_button = remove_mb.addButton(
            "&Cancel", QMessageBox.ButtonRole.DestructiveRole
        )
        remove_mb.addButton("&Remove", QMessageBox.ButtonRole.RejectRole)
        remove_mb.setDefaultButton(cancel_button)
        result = remove_mb.exec_()

        if result == 1:
            callback()

    def clear_layout(self, layout_item: QLayout):
        for i in reversed(range(layout_item.count())):
            child = layout_item.itemAt(i)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                self.clear_layout(child.layout())

    def clear_field_layout(self, layout_item: QLayout):
        for i in reversed(range(layout_item.count())):
            child = layout_item.itemAt(i)

            if child.widget():
                if child.widget() in [self.afb_container, self.afm]:
                    continue
                else:
                    child.widget().deleteLater()
            elif child.layout():
                self.clear_field_layout(child.layout())

    def zero_items(self):
        if self.selected or not self.initialized:
            self.file_label.setText("No Items Selected")
            self.file_label.setFilePath("")
            self.file_label.setCursor(Qt.CursorShape.ArrowCursor)

            self.dimensions_label.setText("")
            self.preview_img.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            self.preview_img.setCursor(Qt.CursorShape.ArrowCursor)

            ratio: float = self.devicePixelRatio()
            self.thumb_renderer.render(
                timestamp=time.time(),
                filepath="",
                base_size=(512, 512),
                pixel_ratio=ratio,
                is_loading=True,
                update_on_ratio_change=True,
            )
            try:
                self.preview_img.clicked.disconnect()
            except RuntimeError:
                pass
            for container in self.containers:
                container.setHidden(True)

        self.selected = list(self.driver.selected)
        self.add_field_button.setHidden(True)

    def one_item(self, window_title: str) -> str:
        if self.lib.root_path is None:
            raise ValueError

        # 1 Selected Entry
        selected = self.driver.selected[0]
        if isinstance(selected, EntrySearchResult):
            item: Entry = self.lib.get_entry_and_fields(entry_id=selected.id)
            # If a new selection is made, update the thumbnail and filepath.
            if not self.selected or self.selected != self.driver.selected:
                filepath = str(self.lib.root_path / item.path)
                window_title = filepath
                self.file_label.setFilePath(filepath)

                ratio: float = self.devicePixelRatio()
                self.thumb_renderer.render(
                    timestamp=time.time(),
                    filepath=filepath,
                    base_size=(512, 512),
                    pixel_ratio=ratio,
                    update_on_ratio_change=True,
                )
                self.file_label.setText("\u200b".join(filepath))
                self.file_label.setCursor(Qt.CursorShape.PointingHandCursor)

                self.preview_img.setContextMenuPolicy(
                    Qt.ContextMenuPolicy.ActionsContextMenu
                )
                self.preview_img.setCursor(Qt.CursorShape.PointingHandCursor)

                self.opener = FileOpenerHelper(filepath)
                self.open_file_action.triggered.connect(self.opener.open_file)
                self.open_explorer_action.triggered.connect(self.opener.open_explorer)

                # TODO: Do this somewhere else, this is just here temporarily.
                extension = os.path.splitext(filepath)[1][1:].lower()
                try:
                    image = None
                    if extension in IMAGE_TYPES:
                        image = Image.open(filepath)
                    elif extension in RAW_IMAGE_TYPES:
                        with rawpy.imread(filepath) as raw:  # type: ignore
                            rgb = raw.postprocess()  # type: ignore
                            image = Image.new(
                                mode="L",
                                size=(rgb.shape[1], rgb.shape[0]),  # type: ignore
                                color="black",
                            )
                    elif extension in VIDEO_TYPES:
                        video = cv2.VideoCapture(filepath)
                        video.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        _, frame = video.read()
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        image = Image.fromarray(frame)

                    if not image:
                        raise UnidentifiedImageError

                    # Stats for specific file types are displayed here.
                    if extension in (IMAGE_TYPES + VIDEO_TYPES + RAW_IMAGE_TYPES):
                        self.dimensions_label.setText(
                            f"{extension.upper()}  •  {format_size(os.stat(filepath).st_size)}\n{image.width} x {image.height} px"
                        )
                    else:
                        self.dimensions_label.setText(f"{extension.upper()}")

                except (
                    UnidentifiedImageError,
                    FileNotFoundError,
                    cv2.error,
                    DecompressionBombError,
                ) as e:
                    self.dimensions_label.setText(
                        f"{extension.upper()}  •  {format_size(os.stat(filepath).st_size)}"
                    )
                    logging.info(
                        f"[PreviewPanel][ERROR] Couldn't Render thumbnail for {filepath} (because of {e})"
                    )

                try:
                    self.preview_img.clicked.disconnect()
                except RuntimeError:
                    pass
                self.preview_img.clicked.connect(
                    lambda checked=False, filepath=filepath: open_file(filepath)
                )

            self.selected = list(self.driver.selected)
            for index, field in enumerate(item.fields):
                self.write_container(index, field)

            # Hide leftover containers
            if len(self.containers) > len(item.fields):
                for index, c in enumerate(self.containers):
                    if index > (len(item.fields) - 1):
                        c.setHidden(True)

            self.add_field_button.setHidden(False)

        return window_title

    def multiple_items(self):
        if self.selected != self.driver.selected:
            self.file_label.setText(f"{len(self.driver.selected)} Items Selected")
            self.file_label.setCursor(Qt.CursorShape.ArrowCursor)
            self.file_label.setFilePath("")
            self.dimensions_label.setText("")

            self.preview_img.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            self.preview_img.setCursor(Qt.CursorShape.ArrowCursor)

            ratio: float = self.devicePixelRatio()
            self.thumb_renderer.render(
                timestamp=time.time(),
                filepath="",
                base_size=(512, 512),
                pixel_ratio=ratio,
                is_loading=True,
                update_on_ratio_change=True,
            )
            try:
                self.preview_img.clicked.disconnect()
            except RuntimeError:
                pass

        self.common_fields: set[Field] = set()
        self.mixed_fields: list[Field] = []

        all_fields: list[set[Field]] = []

        for selected in self.driver.selected:
            if isinstance(selected, EntrySearchResult):
                item = self.lib.get_entry_and_fields(entry_id=selected.id)
                all_fields.append(set(item.fields))

        result = all_fields[0].copy()
        for set_ in all_fields[1:]:
            result.intersection_update(set_)

        self.common_fields = result

        for set_ in all_fields:
            mixed = set_.difference(self.common_fields)
            self.mixed_fields.extend(mixed)

        self.mixed_fields = sorted(self.mixed_fields, key=lambda field: field.name)

        self.selected = self.driver.selected.copy()

        for index, field in enumerate(self.common_fields):
            logging.info(f"ci:{index}, f:{field.id}")
            self.write_container(index, field)
        for index, field in enumerate(self.mixed_fields, start=len(self.common_fields)):
            logging.info(f"mi:{index}, f:{field.id}")
            self.write_container(index, field, mixed=True)

        # Hide leftover containers
        if len(self.containers) > len(self.common_fields) + len(self.mixed_fields):
            for index, c in enumerate(self.containers):
                if index > (len(self.common_fields) + len(self.mixed_fields) - 1):
                    c.setHidden(True)

        self.add_field_button.setHidden(False)
