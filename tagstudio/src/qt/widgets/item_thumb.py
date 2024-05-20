# Copyright (C) 2024 Travis Abendshien (CyanVoxel).
# Licensed under the GPL-3.0 License.
# Created for TagStudio: https://github.com/CyanVoxel/TagStudio


import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

from PIL import Image, ImageQt
from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QAction, QEnterEvent, QPixmap
from PySide6.QtWidgets import (
    QBoxLayout,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from src.alt_core.library import Library
from src.alt_core.types import (
    CollationSearchResult,
    EntrySearchResult,
    SearchResult,
)
from src.core.constants import AUDIO_TYPES, IMAGE_TYPES, VIDEO_TYPES
from src.database.table_declarations.tag import Tag
from src.qt.flowlayout import FlowWidget
from src.qt.helpers.file_opener import FileOpenerHelper
from src.qt.widgets.thumb_button import ThumbButton
from src.qt.widgets.thumb_renderer import ThumbRenderer

if TYPE_CHECKING:
    from src.qt.widgets.preview_panel import PreviewPanel

ERROR = "[ERROR]"
WARNING = "[WARNING]"
INFO = "[INFO]"

DEFAULT_META_TAG_FIELD = 8

logging.basicConfig(format="%(message)s", level=logging.INFO)


class ItemThumb(FlowWidget):
    """
    The thumbnail widget for a library item (Entry, Collation, Tag Group, etc.).
    """

    update_cutoff: float = time.time()

    collation_icon_128: Image.Image = Image.open(
        os.path.normpath(
            f"{Path(__file__).parents[3]}/resources/qt/images/collation_icon_128.png"
        )
    )
    collation_icon_128.load()

    tag_group_icon_128: Image.Image = Image.open(
        os.path.normpath(
            f"{Path(__file__).parents[3]}/resources/qt/images/tag_group_icon_128.png"
        )
    )
    tag_group_icon_128.load()

    small_text_style = (
        "background-color:rgba(0, 0, 0, 192);"
        "font-family:Oxanium;"
        "font-weight:bold;"
        "font-size:12px;"
        "border-radius:3px;"
        "padding-top: 4px;"
        "padding-right: 1px;"
        "padding-bottom: 1px;"
        "padding-left: 1px;"
    )

    med_text_style = (
        "background-color:rgba(0, 0, 0, 192);"
        "font-family:Oxanium;"
        "font-weight:bold;"
        "font-size:18px;"
        "border-radius:3px;"
        "padding-top: 4px;"
        "padding-right: 1px;"
        "padding-bottom: 1px;"
        "padding-left: 1px;"
    )

    def __init__(
        self,
        search_result: Optional[SearchResult],
        library: Library,
        preview_panel: "PreviewPanel",
        thumb_size: tuple[int, int],
    ):
        """Modes: entry, collation, tag_group"""
        super().__init__()
        self.search_result = search_result
        self.lib = library
        self.preview_panel = preview_panel
        self.isFavorite: bool = False
        self.isArchived: bool = False
        self.thumb_size: tuple[int, int] = thumb_size
        self.setMinimumSize(*thumb_size)
        self.setMaximumSize(*thumb_size)
        check_size = 24

        # +----------+
        # |   ARC FAV| Top Right: Favorite & Archived Badges
        # |          |
        # |          |
        # |EXT      #| Lower Left: File Type, Tag Group Icon, or Collation Icon
        # +----------+ Lower Right: Collation Count, Video Length, or Word Count

        # Thumbnail ============================================================

        # +----------+
        # |*--------*|
        # ||        ||
        # ||        ||
        # |*--------*|
        # +----------+
        self.base_layout = QVBoxLayout(self)
        self.base_layout.setObjectName("baseLayout")
        self.base_layout.setContentsMargins(0, 0, 0, 0)

        # +----------+
        # |[~~~~~~~~]|
        # |          |
        # |          |
        # |          |
        # +----------+
        self.top_layout = QHBoxLayout()
        self.top_layout.setObjectName("topLayout")
        self.top_layout.setContentsMargins(6, 6, 6, 6)
        self.top_container = QWidget()
        self.top_container.setLayout(self.top_layout)
        self.base_layout.addWidget(self.top_container)

        # +----------+
        # |[~~~~~~~~]|
        # |     ^    |
        # |     |    |
        # |     v    |
        # +----------+
        self.base_layout.addStretch(2)

        # +----------+
        # |[~~~~~~~~]|
        # |     ^    |
        # |     v    |
        # |[~~~~~~~~]|
        # +----------+
        self.bottom_layout = QHBoxLayout()
        self.bottom_layout.setObjectName("bottomLayout")
        self.bottom_layout.setContentsMargins(6, 6, 6, 6)
        self.bottom_container = QWidget()
        self.bottom_container.setLayout(self.bottom_layout)
        self.base_layout.addWidget(self.bottom_container)

        self.thumb_button = ThumbButton(self, thumb_size)
        self.renderer = ThumbRenderer()
        self.renderer.updated.connect(
            lambda timestamp, image, size, extension: (  # type: ignore
                self.update_thumb(timestamp=timestamp, image=image),  # type: ignore
                self.update_size(timestamp=timestamp, size=size),  # type: ignore
                self.set_extension(ext=extension),  # type: ignore
            )
        )
        self.thumb_button.setFlat(True)

        self.thumb_button.setLayout(self.base_layout)

        self.thumb_button.setContextMenuPolicy(Qt.ContextMenuPolicy.ActionsContextMenu)
        self.opener = FileOpenerHelper("")
        open_file_action = QAction("Open file", self)
        open_file_action.triggered.connect(self.opener.open_file)
        open_explorer_action = QAction("Open file in explorer", self)
        open_explorer_action.triggered.connect(self.opener.open_explorer)
        self.thumb_button.addAction(open_file_action)
        self.thumb_button.addAction(open_explorer_action)

        # Static Badges ========================================================

        # Item Type Badge ------------------------------------------------------
        # Used for showing the Tag Group / Collation icons.
        # Mutually exclusive with the File Extension Badge.
        self.item_type_badge = QLabel()
        self.item_type_badge.setObjectName("itemBadge")
        self.item_type_badge.setPixmap(
            QPixmap.fromImage(
                ImageQt.ImageQt(
                    ItemThumb.collation_icon_128.resize(
                        (check_size, check_size), Image.Resampling.BILINEAR
                    )
                )
            )
        )
        self.item_type_badge.setMinimumSize(check_size, check_size)
        self.item_type_badge.setMaximumSize(check_size, check_size)
        self.bottom_layout.addWidget(self.item_type_badge)

        # File Extension Badge -------------------------------------------------
        # Mutually exclusive with the File Extension Badge.
        self.ext_badge = QLabel()
        self.ext_badge.setObjectName("extBadge")
        self.ext_badge.setStyleSheet(ItemThumb.small_text_style)
        self.bottom_layout.addWidget(self.ext_badge)

        self.bottom_layout.addStretch(2)

        # Count Badge ----------------------------------------------------------
        # Used for Tag Group + Collation counts, video length, word count, etc.
        self.count_badge = QLabel()
        self.count_badge.setObjectName("countBadge")
        self.count_badge.setText("-:--")
        self.count_badge.setStyleSheet(ItemThumb.small_text_style)
        self.bottom_layout.addWidget(
            self.count_badge, alignment=Qt.AlignmentFlag.AlignBottom
        )

        self.top_layout.addStretch(2)

        # Intractable Badges ===================================================
        self.check_box_container = QWidget()
        self.check_box_layout = QHBoxLayout()
        self.check_box_layout.setDirection(QBoxLayout.Direction.RightToLeft)
        self.check_box_layout.setContentsMargins(0, 0, 0, 0)
        self.check_box_layout.setSpacing(6)
        self.check_box_container.setLayout(self.check_box_layout)
        self.top_layout.addWidget(self.check_box_container)

        # Favorite Badge -------------------------------------------------------
        self.favorite_badge = QCheckBox()
        self.favorite_badge.setObjectName("favBadge")
        self.favorite_badge.setToolTip("Favorite")
        self.favorite_badge.setStyleSheet(
            f"QCheckBox::indicator{{width: {check_size}px;height: {check_size}px;}}"
            f"QCheckBox::indicator::unchecked{{image: url(:/images/star_icon_empty_128.png)}}"
            f"QCheckBox::indicator::checked{{image: url(:/images/star_icon_filled_128.png)}}"
        )
        self.favorite_badge.setMinimumSize(check_size, check_size)
        self.favorite_badge.setMaximumSize(check_size, check_size)
        self.favorite_badge.stateChanged.connect(self.on_favorite_check)
        self.check_box_layout.addWidget(self.favorite_badge)
        self.favorite_badge.setHidden(True)

        # Archive Badge --------------------------------------------------------
        self.archived_badge = QCheckBox()
        self.archived_badge.setObjectName("archiveBadge")
        self.archived_badge.setToolTip("Archive")
        self.archived_badge.setStyleSheet(
            f"QCheckBox::indicator{{width: {check_size}px;height: {check_size}px;}}"
            f"QCheckBox::indicator::unchecked{{image: url(:/images/box_icon_empty_128.png)}}"
            f"QCheckBox::indicator::checked{{image: url(:/images/box_icon_filled_128.png)}}"
        )
        self.archived_badge.setMinimumSize(check_size, check_size)
        self.archived_badge.setMaximumSize(check_size, check_size)
        self.archived_badge.stateChanged.connect(self.on_archived_check)
        self.check_box_layout.addWidget(self.archived_badge)
        self.archived_badge.setHidden(True)

        self.set_search_result(search_result=search_result)

    def set_search_result(self, search_result: SearchResult | None) -> None:
        if search_result is None:
            self.unsetCursor()
            self.thumb_button.setHidden(True)
        elif isinstance(search_result, EntrySearchResult):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.thumb_button.setHidden(False)
            self.check_box_container.setHidden(False)
            self.item_type_badge.setHidden(True)
            self.count_badge.setStyleSheet(ItemThumb.small_text_style)
            self.count_badge.setHidden(True)
            self.ext_badge.setHidden(True)
        elif isinstance(search_result, CollationSearchResult):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.thumb_button.setHidden(False)
            self.check_box_container.setHidden(True)
            self.ext_badge.setHidden(True)
            self.count_badge.setStyleSheet(ItemThumb.med_text_style)
            self.count_badge.setHidden(False)
            self.item_type_badge.setHidden(False)
        else:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.thumb_button.setHidden(False)
            self.ext_badge.setHidden(True)
            self.count_badge.setHidden(False)
            self.item_type_badge.setHidden(False)

        self.search_result = search_result

    def set_extension(self, ext: str) -> None:
        if ext and ext not in IMAGE_TYPES or ext in ["gif", "apng"]:
            self.ext_badge.setHidden(False)
            self.ext_badge.setText(ext.upper())
            if ext in VIDEO_TYPES + AUDIO_TYPES:
                self.count_badge.setHidden(False)
        else:
            if isinstance(self.search_result, EntrySearchResult):
                self.ext_badge.setHidden(True)
                self.count_badge.setHidden(True)

    def set_count(self, count: str) -> None:
        if count:
            self.count_badge.setHidden(False)
            self.count_badge.setText(count)
        else:
            if isinstance(self.search_result, EntrySearchResult):
                self.ext_badge.setHidden(True)
                self.count_badge.setHidden(True)

    def update_thumb(self, timestamp: float, image: QPixmap | None = None):
        """Updates attributes of a thumbnail element."""
        # logging.info(f'[GUI] Updating Thumbnail for element {id(element)}: {id(image) if image else None}')
        if timestamp > ItemThumb.update_cutoff:
            self.thumb_button.setIcon(image if image else QPixmap())
            # element.repaint()

    def update_size(self, timestamp: float, size: QSize):
        """Updates attributes of a thumbnail element."""
        # logging.info(f'[GUI] Updating size for element {id(element)}:  {size.__str__()}')
        if timestamp > ItemThumb.update_cutoff:
            if self.thumb_button.iconSize != size:  # type: ignore
                self.thumb_button.setIconSize(size)
                self.thumb_button.setMinimumSize(size)
                self.thumb_button.setMaximumSize(size)

    def update_clickable(self, clickable: Callable[[], Any]):
        """Updates attributes of a thumbnail element."""
        # logging.info(f'[GUI] Updating Click Event for element {id(element)}: {id(clickable) if clickable else None}')
        try:
            self.thumb_button.clicked.disconnect()
        except RuntimeError:
            pass
        if callable(clickable):
            self.thumb_button.clicked.connect(clickable)

    def update_badges(self):
        if self.search_result is None:
            raise ValueError

        if not isinstance(self.search_result, EntrySearchResult):
            return

        archived, favorited = self.lib.entry_archived_favorited_status(
            entry=self.search_result.id
        )

        self.search_result.archived = archived
        self.search_result.favorited = favorited

        self.assign_archived(self.search_result.archived)
        self.assign_favorite(self.search_result.favorited)

    def set_item_id(self, id: int):
        """
        also sets the filepath for the file opener
        """
        self.item_id = id
        if id == -1:
            return

    def assign_favorite(self, value: bool):
        # Switching mode to None to bypass mode-specific operations when the
        # checkbox's state changes.
        cached_search_result = self.search_result
        self.search_result = None
        self.isFavorite = value
        self.favorite_badge.setChecked(value)
        if not self.thumb_button.underMouse():
            self.favorite_badge.setHidden(not self.isFavorite)
        self.search_result = cached_search_result

    def assign_archived(self, value: bool):
        # Switching mode to None to bypass mode-specific operations when the
        # checkbox's state changes.
        cached_search_result = self.search_result
        self.search_result = None
        self.isArchived = value
        self.archived_badge.setChecked(value)
        if not self.thumb_button.underMouse():
            self.archived_badge.setHidden(not self.isArchived)
        self.search_result = cached_search_result

    def show_check_badges(self, show: bool):
        if isinstance(self.search_result, EntrySearchResult):
            self.favorite_badge.setHidden(
                True if (not show and not self.isFavorite) else False
            )
            self.archived_badge.setHidden(
                True if (not show and not self.isArchived) else False
            )

    def enterEvent(self, event: QEnterEvent) -> None:
        self.show_check_badges(True)
        return super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self.show_check_badges(False)
        return super().leaveEvent(event)

    def on_archived_check(self):
        if isinstance(self.search_result, EntrySearchResult):
            self.toggle_item_tag(self.archived_badge.isChecked(), self.lib.archived_tag)

    def on_favorite_check(self):
        if isinstance(self.search_result, EntrySearchResult):
            self.toggle_item_tag(self.favorite_badge.isChecked(), self.lib.favorite_tag)

    def toggle_item_tag(self, toggle_value: bool, tag: Tag):
        if self.search_result is None:
            raise ValueError

        def toggle_tag(search_result: SearchResult):
            if toggle_value:
                self.lib.add_tag_to_entry_meta_tags(
                    tag=tag,
                    entry_id=search_result.id,
                )
            else:
                self.lib.remove_tag_from_entry_meta_tags(
                    tag=tag,
                    entry_id=search_result.id,
                )

        # Is the badge a part of the selection?
        if self.search_result in self.preview_panel.driver.selected:
            # Yes, add chosen tag to all selected.
            for search_result in self.preview_panel.driver.selected:
                toggle_tag(search_result=search_result)

            # Update all selected badges
            self.preview_panel.driver.update_badges()
        else:
            # No, add tag to the entry this badge is on.
            toggle_tag(search_result=self.search_result)

            # Update just the one badge
            self.update_badges()

        if self.preview_panel.isOpen:
            self.preview_panel.update_widgets()
