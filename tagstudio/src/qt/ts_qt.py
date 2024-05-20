# Copyright (C) 2024 Travis Abendshien (CyanVoxel).
# Licensed under the GPL-3.0 License.
# Created for TagStudio: https://github.com/CyanVoxel/TagStudio

# SIGTERM handling based on the implementation by Virgil Dupras for dupeGuru:
# https://github.com/arsenetar/dupeguru/blob/master/run.py#L71

"""A Qt driver for TagStudio."""

import ctypes
import logging
import math
import os
import sys
import time
import webbrowser
from argparse import Namespace
from datetime import datetime as dt
from itertools import batched
from pathlib import Path
from queue import Queue
from signal import Signals
from typing import Any, Callable

from humanfriendly import format_timespan
from PIL import Image
from PySide6 import QtCore
from PySide6.QtCore import QObject, QSettings, Qt, QThread, QThreadPool, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFontDatabase,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QPixmap,
)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLineEdit,
    QMenu,
    QMenuBar,
    QPushButton,
    QScrollArea,
    QSplashScreen,
    QSplitter,
    QWidget,
)
from src.alt_core.ts_core import (
    COLLAGE_FOLDER_NAME,
    TS_FOLDER_NAME,
    VERSION,
    VERSION_BRANCH,
    TagStudioCore,
)
from src.alt_core.types import (
    EntrySearchResult,
    Frame,
    Frames,
    SearchResult,
    SettingItems,
)
from src.core.utils.web import strip_web_protocol
from src.qt.flowlayout import FlowLayout
from src.qt.helpers.custom_runnable import CustomRunnable
from src.qt.helpers.function_iterator import FunctionIterator
from src.qt.main_window import Ui_MainWindow
from src.qt.modals.build_tag import BuildTagPanel
from src.qt.modals.file_extension import FileExtensionModal
from src.qt.modals.fix_dupes import FixDupeFilesModal
from src.qt.modals.fix_unlinked import FixUnlinkedEntriesModal
from src.qt.modals.folders_to_tags import FoldersToTagsModal
from src.qt.modals.tag_database import TagDatabasePanel
from src.qt.resources_rc import qInitResources
from src.qt.widgets.collage_icon import CollageIconRenderer
from src.qt.widgets.item_thumb import ItemThumb
from src.qt.widgets.panel import PanelModal, PanelWidget
from src.qt.widgets.preview_panel import PreviewPanel
from src.qt.widgets.progress import ProgressWidget
from src.qt.widgets.thumb_renderer import ThumbRenderer

# This import has side-effect of import PySide resources
LOAD_RESOURCES = qInitResources

# SIGQUIT is not defined on Windows
if sys.platform == "win32":
    from signal import SIGINT, SIGTERM, signal

    SIGQUIT = SIGTERM
else:
    from signal import SIGINT, SIGQUIT, SIGTERM, signal

ERROR = "[ERROR]"
WARNING = "[WARNING]"
INFO = "[INFO]"

logging.basicConfig(format="%(message)s", level=logging.DEBUG)


class NavigationState:
    """Represents a state of the Library grid view."""

    def __init__(
        self,
        contents: Frame,
        scrollbar_pos: int,
        page_index: int,
        page_count: int,
        search_text: str | None = None,
        thumb_size: int | None = None,
        spacing: int | None = None,
    ) -> None:
        self.contents = contents
        self.scrollbar_pos = scrollbar_pos
        self.page_index = page_index
        self.page_count = page_count
        self.search_text = search_text
        self.thumb_size = thumb_size
        self.spacing = spacing


class Consumer(QThread):
    MARKER_QUIT = "MARKER_QUIT"

    def __init__(self, queue: Queue[Any]) -> None:
        self.queue = queue
        QThread.__init__(self)

    def run(self):
        while True:
            try:
                job = self.queue.get()
                if job == self.MARKER_QUIT:
                    break
                job[0](*job[1])
            except RuntimeError:
                pass

    def set_page_count(self, count: int):
        self.page_count = count

    def jump_to_page(self, index: int):
        pass

    def nav_back(self):
        pass

    def nav_forward(self):
        pass


class QtDriver(QObject):
    """A Qt GUI frontend driver for TagStudio."""

    SIGTERM = Signal()

    preview_panel: PreviewPanel

    def __init__(self, core: TagStudioCore, args: Namespace):
        super().__init__()
        self.core: TagStudioCore = core
        self.lib = self.core.lib
        self.args = args
        self.frame_dict: dict[str, Frames] = {}
        self.nav_frames: list[NavigationState] = []
        self.cur_frame_idx: int = -1

        self.branch: str = (" (" + VERSION_BRANCH + ")") if VERSION_BRANCH else ""
        self.base_title: str = f"TagStudio Alpha {VERSION}{self.branch}"

        self.thumb_job_queue: Queue[Any] = Queue()
        self.thumb_threads: list[Consumer] = []
        self.thumb_cutoff: float = time.time()

        self.selected: list[SearchResult] = []

        self.SIGTERM.connect(self.handle_SIGTERM)

        if self.args.config_file:
            path = Path(self.args.config_file)
            if not path.exists():
                logging.warning(
                    f"[QT DRIVER] Config File does not exist creating {str(path)}"
                )
            logging.info(f"[QT DRIVER] Using Config File {str(path)}")
            self.settings = QSettings(str(path), QSettings.Format.IniFormat)
        else:
            self.settings = QSettings(
                QSettings.Format.IniFormat,
                QSettings.Scope.UserScope,
                "TagStudio",
                "TagStudio",
            )
            logging.info(
                f"[QT DRIVER] Config File not specified, defaulting to {self.settings.fileName()}"
            )

        max_threads = os.cpu_count() or 1
        if args.ci:
            max_threads = 1
        for i in range(max_threads):
            thread = Consumer(self.thumb_job_queue)
            thread.setObjectName(f"ThumbRenderer_{i}")
            self.thumb_threads.append(thread)
            thread.start()

    def open_library_from_dialog(self):
        dir = QFileDialog.getExistingDirectory(
            parent=None,
            caption="Open/Create Library",
            dir="/",
            options=QFileDialog.Option.ShowDirsOnly,
        )
        if dir not in (None, ""):
            self.open_library(dir)

    def signal_handler(self, sig: Signals):
        if sig in (SIGINT, SIGTERM, SIGQUIT):
            self.SIGTERM.emit()

    def setup_signals(self):
        signal(SIGINT, self.signal_handler)  # type: ignore
        signal(SIGTERM, self.signal_handler)  # type: ignore
        signal(SIGQUIT, self.signal_handler)  # type: ignore

    def start(self) -> None:
        """Launches the main Qt window."""

        loader = QUiLoader()

        if os.name == "nt":
            sys.argv += ["-platform", "windows:darkmode=2"]

        app = QApplication(sys.argv)
        app.setStyle("Fusion")

        home_path = str(Path(__file__).parent / "ui/home.ui")
        icon_path = str(Path(__file__).parents[2] / "resources/icon.png")

        # Handle OS signals
        self.setup_signals()
        # Allow processing input from console, eg. SIGTERM
        timer = QTimer()
        timer.start(500)
        timer.timeout.connect(lambda: None)

        self.main_window = Ui_MainWindow()
        self.main_window.setWindowTitle(self.base_title)
        self.main_window.mousePressEvent = self.mouse_navigation  # type: ignore

        splash_pixmap = QPixmap(":/images/splash.png")
        self.splash = QSplashScreen(splash_pixmap, Qt.WindowStaysOnTopHint)  # type: ignore
        self.splash.show()

        if os.name == "nt":
            appid = "cyanvoxel.tagstudio.9"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(appid)  # type: ignore

        if sys.platform != "darwin":
            icon = QIcon()
            icon.addFile(icon_path)
            app.setWindowIcon(icon)

        menu_bar = QMenuBar(self.main_window)
        menu_bar.setNativeMenuBar(True)

        file_menu = QMenu("&File", menu_bar)
        edit_menu = QMenu("&Edit", menu_bar)
        tools_menu = QMenu("&Tools", menu_bar)
        macros_menu = QMenu("&Macros", menu_bar)
        window_menu = QMenu("&Window", menu_bar)
        help_menu = QMenu("&Help", menu_bar)

        self.main_window.setMenuBar(menu_bar)

        # File Menu ============================================================
        open_library_action = QAction("&Open/Create Library", menu_bar)
        open_library_action.triggered.connect(self.open_library_from_dialog)
        open_library_action.setShortcut(
            QtCore.QKeyCombination(
                QtCore.Qt.KeyboardModifier.ControlModifier,
                QtCore.Qt.Key.Key_O,
            )
        )
        open_library_action.setToolTip("Ctrl+O")

        file_menu.addAction(open_library_action)  # type: ignore

        save_library_backup_action = QAction("&Save Library Backup", menu_bar)
        save_library_backup_action.triggered.connect(
            lambda: self.callback_library_needed_check(self.backup_library)  # type: ignore
        )
        save_library_backup_action.setShortcut(
            QtCore.QKeyCombination(
                QtCore.Qt.KeyboardModifier(
                    QtCore.Qt.KeyboardModifier.ControlModifier
                    | QtCore.Qt.KeyboardModifier.ShiftModifier
                ),
                QtCore.Qt.Key.Key_S,
            )
        )
        save_library_backup_action.setStatusTip("Ctrl+Shift+S")

        file_menu.addAction(save_library_backup_action)  # type: ignore

        file_menu.addSeparator()

        add_new_files_action = QAction("&Refresh Directories", menu_bar)
        add_new_files_action.triggered.connect(
            lambda: self.callback_library_needed_check(self.add_new_files_callback)  # type: ignore
        )
        add_new_files_action.setShortcut(
            QtCore.QKeyCombination(
                QtCore.Qt.KeyboardModifier(QtCore.Qt.KeyboardModifier.ControlModifier),
                QtCore.Qt.Key.Key_R,
            )
        )
        add_new_files_action.setStatusTip("Ctrl+R")
        file_menu.addAction(add_new_files_action)  # type: ignore

        file_menu.addSeparator()

        close_library_action = QAction("&Close Library", menu_bar)
        close_library_action.triggered.connect(lambda: self.close_library())  # type: ignore
        file_menu.addAction(close_library_action)  # type: ignore

        # Edit Menu ============================================================
        new_tag_action = QAction("New &Tag", menu_bar)
        new_tag_action.triggered.connect(lambda: self.add_tag_action_callback())  # type: ignore
        new_tag_action.setShortcut(
            QtCore.QKeyCombination(
                QtCore.Qt.KeyboardModifier(QtCore.Qt.KeyboardModifier.ControlModifier),
                QtCore.Qt.Key.Key_T,
            )
        )
        new_tag_action.setToolTip("Ctrl+T")
        edit_menu.addAction(new_tag_action)  # type: ignore
        edit_menu.addSeparator()

        manage_file_extensions_action = QAction("Ignored File Extensions", menu_bar)
        manage_file_extensions_action.triggered.connect(
            lambda: self.show_file_extension_modal()  # type: ignore
        )
        edit_menu.addAction(manage_file_extensions_action)  # type: ignore

        tag_database_action = QAction("Manage Tags", menu_bar)
        tag_database_action.triggered.connect(lambda: self.show_tag_database())  # type: ignore
        edit_menu.addAction(tag_database_action)  # type: ignore

        check_action = QAction("Open library on start", self)
        check_action.setCheckable(True)
        check_action.setChecked(
            self.settings.value(SettingItems.START_LOAD_LAST, True, type=bool)  # type: ignore
        )
        check_action.triggered.connect(
            lambda checked: self.settings.setValue(  # type: ignore
                SettingItems.START_LOAD_LAST, checked
            )
        )
        window_menu.addAction(check_action)  # type: ignore

        # Tools Menu ===========================================================
        fix_unlinked_entries_action = QAction("Fix &Unlinked Entries", menu_bar)
        fue_modal = FixUnlinkedEntriesModal(self.lib, self)
        fix_unlinked_entries_action.triggered.connect(lambda: fue_modal.show())
        tools_menu.addAction(fix_unlinked_entries_action)  # type: ignore

        fix_dupe_files_action = QAction("Fix Duplicate &Files", menu_bar)
        fdf_modal = FixDupeFilesModal(self.lib, self)
        fix_dupe_files_action.triggered.connect(lambda: fdf_modal.show())
        tools_menu.addAction(fix_dupe_files_action)  # type: ignore

        create_collage_action = QAction("Create Collage", menu_bar)
        create_collage_action.triggered.connect(lambda: self.create_collage())
        tools_menu.addAction(create_collage_action)  # type: ignore

        # Macros Menu ==========================================================
        self.autofill_action = QAction("Autofill", menu_bar)
        self.autofill_action.triggered.connect(
            lambda: (
                self.run_macros(
                    "autofill", [x[1] for x in self.selected if x[0] == ItemType.ENTRY]
                ),
                self.preview_panel.update_widgets(),
            )
        )
        macros_menu.addAction(self.autofill_action)  # type: ignore

        self.sort_fields_action = QAction("&Sort Fields", menu_bar)
        self.sort_fields_action.triggered.connect(
            lambda: (
                self.run_macros(
                    "sort-fields",
                    [x[1] for x in self.selected if x[0] == ItemType.ENTRY],
                ),
                self.preview_panel.update_widgets(),
            )
        )
        self.sort_fields_action.setShortcut(
            QtCore.QKeyCombination(
                QtCore.Qt.KeyboardModifier(QtCore.Qt.KeyboardModifier.AltModifier),
                QtCore.Qt.Key.Key_S,
            )
        )
        self.sort_fields_action.setToolTip("Alt+S")
        macros_menu.addAction(self.sort_fields_action)  # type: ignore

        show_libs_list_action = QAction("Show Recent Libraries", menu_bar)
        show_libs_list_action.setCheckable(True)
        show_libs_list_action.setChecked(
            self.settings.value(SettingItems.WINDOW_SHOW_LIBS, True, type=bool)  # type: ignore
        )
        show_libs_list_action.triggered.connect(
            lambda checked: (  # type: ignore
                self.settings.setValue(SettingItems.WINDOW_SHOW_LIBS, checked),  # type: ignore
                self.toggle_libs_list(checked),  # type: ignore
            )  # type: ignore
        )
        window_menu.addAction(show_libs_list_action)  # type: ignore

        folders_to_tags_action = QAction("Folders to Tags", menu_bar)
        ftt_modal = FoldersToTagsModal(self.lib, self)
        folders_to_tags_action.triggered.connect(lambda: ftt_modal.show())
        macros_menu.addAction(folders_to_tags_action)  # type: ignore

        # Help Menu ==========================================================
        self.repo_action = QAction("Visit GitHub Repository", menu_bar)
        self.repo_action.triggered.connect(
            lambda: webbrowser.open("https://github.com/TagStudioDev/TagStudio")
        )
        help_menu.addAction(self.repo_action)  # type: ignore

        self.set_macro_menu_viability()

        menu_bar.addMenu(file_menu)
        menu_bar.addMenu(edit_menu)
        menu_bar.addMenu(tools_menu)
        menu_bar.addMenu(macros_menu)
        menu_bar.addMenu(window_menu)
        menu_bar.addMenu(help_menu)

        self.preview_panel = PreviewPanel(self.lib, self)
        layout: QSplitter = self.main_window.splitter
        layout.addWidget(self.preview_panel)

        QFontDatabase.addApplicationFont(
            os.path.normpath(
                f"{Path(__file__).parents[2]}/resources/qt/fonts/Oxanium-Bold.ttf"
            )
        )

        self.thumb_size = 128
        self.max_results = 500
        self.item_thumbs: list[ItemThumb] = []
        self.thumb_renderers: list[ThumbRenderer] = []
        self.collation_thumb_size = math.ceil(self.thumb_size * 2)

        self.init_library_window()

        lib = None
        if self.args.open:
            lib = self.args.open
        elif self.settings.value(SettingItems.START_LOAD_LAST, True, type=bool):
            lib = self.settings.value(SettingItems.LAST_LIBRARY)

        if lib:
            self.splash.showMessage(
                f'Opening Library "{lib}"...',
                int(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter),
                QColor("#9782ff"),
            )
            self.open_library(lib)

        if self.args.ci:
            # gracefully terminate the app in CI environment
            self.thumb_job_queue.put((self.SIGTERM.emit, []))

        app.exec()

        self.shutdown()

    def init_library_window(self):
        self._init_thumb_grid()

        # TODO: Put this into its own method that copies the font file(s) into memory
        # so the resource isn't being used, then store the specific size variations
        # in a global dict for methods to access for different DPIs.
        # adj_font_size = math.floor(12 * self.main_window.devicePixelRatio())
        # self.ext_font = ImageFont.truetype(os.path.normpath(f'{Path(__file__).parents[2]}/resources/qt/fonts/Oxanium-Bold.ttf'), adj_font_size)

        search_button: QPushButton = self.main_window.searchButton
        search_button.clicked.connect(
            lambda: self.filter_items(self.main_window.searchField.text())
        )
        search_field: QLineEdit = self.main_window.searchField
        search_field.returnPressed.connect(
            lambda: self.filter_items(self.main_window.searchField.text())
        )

        back_button: QPushButton = self.main_window.backButton
        back_button.clicked.connect(self.nav_back)
        forward_button: QPushButton = self.main_window.forwardButton
        forward_button.clicked.connect(self.nav_forward)

        self.frame_dict = {}
        self.main_window.pagination.index.connect(
            lambda index: (  # type: ignore
                self.nav_forward(
                    *self.get_frame_contents(
                        index,  # type: ignore
                        self.nav_frames[self.cur_frame_idx].search_text,  # type: ignore
                    )
                )
            )
        )

        self.nav_frames = []
        self.cur_frame_idx = -1
        self.cur_query = ""
        self.filter_items()
        # self.update_thumbs()

        # self.render_times: list = []
        # self.main_window.setWindowFlag(Qt.FramelessWindowHint)

        # NOTE: Putting this early will result in a white non-responsive
        # window until everything is loaded. Consider adding a splash screen
        # or implementing some clever loading tricks.
        self.main_window.show()
        self.main_window.activateWindow()
        # self.main_window.raise_()
        self.splash.finish(self.main_window)
        self.preview_panel.update_widgets()

    def toggle_libs_list(self, value: bool):
        if value:
            self.preview_panel.libs_flow_container.show()
        else:
            self.preview_panel.libs_flow_container.hide()
        self.preview_panel.update()

    def callback_library_needed_check(self, func: Callable[[], None]):
        """Check if loaded library has valid path before executing the button function"""
        if self.lib.root_path:
            func()

    def handle_SIGTERM(self):
        self.shutdown()

    def shutdown(self):
        """Save Library on Application Exit"""
        if self.lib.root_path:
            self.settings.setValue(SettingItems.LAST_LIBRARY, self.lib.root_path)
            self.settings.sync()
        logging.info("[SHUTDOWN] Ending Thumbnail Threads...")
        for _ in self.thumb_threads:
            self.thumb_job_queue.put(Consumer.MARKER_QUIT)

        # wait for threads to quit
        for thread in self.thumb_threads:
            thread.quit()
            thread.wait()

        QApplication.quit()

    def close_library(self):
        if self.lib.root_path:
            self.main_window.statusbar.showMessage("Closing & Saving Library...")
            start_time = time.time()
            self.settings.setValue(SettingItems.LAST_LIBRARY, self.lib.root_path)
            self.settings.sync()

            self.lib.clear_internal_vars()
            title_text = f"{self.base_title}"
            self.main_window.setWindowTitle(title_text)

            self.nav_frames = []
            self.cur_frame_idx = -1
            self.cur_query = ""
            self.selected.clear()
            self.preview_panel.update_widgets()
            self.filter_items()

            end_time = time.time()
            self.main_window.statusbar.showMessage(
                f"Library Saved and Closed! ({format_timespan(end_time - start_time)})"
            )

    # TODO
    def backup_library(self):
        logging.info("Backing Up Library...")

    def add_tag_action_callback(self):
        self.modal = PanelModal(
            widget=BuildTagPanel(self.lib),
            title="New Tag",
            window_title="Add Tag",
            has_save=True,
        )

        panel: PanelWidget = self.modal.widget

        if not isinstance(panel, BuildTagPanel):
            raise ValueError

        self.modal.saved.connect(
            lambda: (self.lib.create_tag(panel.build_tag()), self.modal.hide())
        )

        self.modal.show()

    def show_tag_database(self):
        self.modal = PanelModal(
            TagDatabasePanel(self.lib), "Library Tags", "Library Tags", has_save=False
        )
        self.modal.show()

    def show_file_extension_modal(self):
        # self.modal = FileExtensionModal(self.lib)
        panel = FileExtensionModal(self.lib)
        self.modal = PanelModal(
            panel, "Ignored File Extensions", "Ignored File Extensions", has_save=True
        )
        self.modal.saved.connect(lambda: (panel.save(), self.filter_items("")))
        self.modal.show()

    def add_new_files_callback(self):
        """Runs when user initiates adding new files to the Library."""

        iterator = FunctionIterator(self.lib.refresh_dir)
        progress_widget = ProgressWidget(
            window_title="Refreshing Directories",
            label_text="Scanning Directories for New Files...\nPreparing...",
            cancel_button_text=None,
            minimum=0,
            maximum=0,
        )
        progress_widget.show()
        iterator.value.connect(lambda x: progress_widget.update_progress(x + 1))  # type: ignore
        iterator.value.connect(
            lambda x: progress_widget.update_label(  # type: ignore
                f'Scanning Directories for New Files...\n{x + 1} File{"s" if x + 1 != 1 else ""} Searched, {len(self.lib.files_not_in_library)} New Files Found'
            )
        )

        runable = CustomRunnable(lambda: iterator.run())
        runable.done.connect(
            lambda: (
                progress_widget.hide(),
                progress_widget.deleteLater(),
                self.filter_items(),
            )
        )  # type: ignore
        QThreadPool.globalInstance().start(runable)  # type: ignore

    def run_macros(self, name: str, entry_ids: list[int]):
        """Runs a specific Macro on a group of given entry_ids."""
        for id in entry_ids:
            self.run_macro(name, id)

    def run_macro(self, name: str, entry_id: int):
        """Runs a specific Macro on an Entry given a Macro name."""
        entry = self.lib.get_entry(entry_id)
        path = os.path.normpath(f"{self.lib.root_path}/{entry.path}/{entry.filename}")
        source = path.split(os.sep)[1].lower()
        if name == "sidecar":
            self.lib.add_generic_data_to_entry(
                self.core.get_gdl_sidecar(path, source), entry_id
            )
        elif name == "autofill":
            self.run_macro("sidecar", entry_id)
            self.run_macro("build-url", entry_id)
            self.run_macro("match", entry_id)
            self.run_macro("clean-url", entry_id)
            self.run_macro("sort-fields", entry_id)
        elif name == "build-url":
            data = {"source": self.core.build_url(entry_id, source)}
            self.lib.add_generic_data_to_entry(data, entry_id)
        elif name == "sort-fields":
            order: list[int] = (
                [0]
                + [1, 2]
                + [9, 17, 18, 19, 20]
                + [8, 7, 6]
                + [4]
                + [3, 21]
                + [10, 14, 11, 12, 13, 22]
                + [5]
            )
            self.lib.sort_fields(entry_id, order)
        elif name == "match":
            self.core.match_conditions(entry_id)
        # elif name == 'scrape':
        # 	self.core.scrape(entry_id)
        elif name == "clean-url":
            # entry = self.lib.get_entry_from_index(entry_id)
            if entry.fields:
                for i, field in enumerate(entry.fields, start=0):
                    if self.lib.get_field_attr(field, "type") == "text_line":
                        self.lib.update_field(
                            entry_id=entry_id,
                            field_id=i,
                            content=strip_web_protocol(
                                self.lib.get_field_attr(field, "content")
                            ),
                            mode="replace",
                        )

    def mouse_navigation(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.ForwardButton:
            self.nav_forward()
        elif event.button() == Qt.MouseButton.BackButton:
            self.nav_back()

    def nav_forward(
        self,
        frame_content: Frame | None = None,
        page_index: int = 0,
        page_count: int = 0,
    ):
        """Navigates a step further into the navigation stack."""
        logging.info(
            f"Calling NavForward with Content:{False if not frame_content else frame_content[0]}, Index:{page_index}, PageCount:{page_count}"
        )

        # Ex. User visits | A ->[B]     |
        #                 | A    B ->[C]|
        #                 | A   [B]<- C |
        #                 |[A]<- B    C |  Previous routes still exist
        #                 | A ->[D]     |  Stack is cut from [:A] on new route

        # Moving forward (w/ or wo/ new content) in the middle of the stack
        original_pos = self.cur_frame_idx
        sb: QScrollArea = self.main_window.scrollArea
        sb_pos = sb.verticalScrollBar().value()
        search_text = self.main_window.searchField.text()

        trimmed = False
        if len(self.nav_frames) > self.cur_frame_idx + 1:
            if frame_content is not None:
                # Trim the nav stack if user is taking a new route.
                self.nav_frames = self.nav_frames[: self.cur_frame_idx + 1]
                if self.nav_frames and not self.nav_frames[self.cur_frame_idx].contents:
                    self.nav_frames.pop()
                    trimmed = True
                self.nav_frames.append(
                    NavigationState(
                        contents=frame_content,
                        scrollbar_pos=0,
                        page_index=page_index,
                        page_count=page_count,
                        search_text=search_text,
                    )
                )
            # Update the last frame's scroll_pos
            self.nav_frames[self.cur_frame_idx].scrollbar_pos = sb_pos
            self.cur_frame_idx += 1 if not trimmed else 0
        # Moving forward at the end of the stack with new content
        elif frame_content is not None:
            # If the current page is empty, don't include it in the new stack.
            if self.nav_frames and not self.nav_frames[self.cur_frame_idx].contents:
                self.nav_frames.pop()
                trimmed = True
            self.nav_frames.append(
                NavigationState(frame_content, 0, page_index, page_count, search_text)
            )
            self.nav_frames[self.cur_frame_idx].scrollbar_pos = sb_pos
            self.cur_frame_idx += 1 if not trimmed else 0

        if (self.cur_frame_idx != original_pos) or (frame_content is not None):
            self.update_thumbs()
            sb.verticalScrollBar().setValue(
                self.nav_frames[self.cur_frame_idx].scrollbar_pos
            )
            self.main_window.searchField.setText(
                self.nav_frames[self.cur_frame_idx].search_text or ""
            )
            self.main_window.pagination.update_buttons(
                self.nav_frames[self.cur_frame_idx].page_count,
                self.nav_frames[self.cur_frame_idx].page_index,
                emit=False,
            )

    def nav_back(self):
        """Navigates a step backwards in the navigation stack."""

        original_pos = self.cur_frame_idx
        sb: QScrollArea = self.main_window.scrollArea
        sb_pos = sb.verticalScrollBar().value()

        if self.cur_frame_idx > 0:
            self.nav_frames[self.cur_frame_idx].scrollbar_pos = sb_pos
            self.cur_frame_idx -= 1
            if self.cur_frame_idx != original_pos:
                self.update_thumbs()
                sb.verticalScrollBar().setValue(
                    self.nav_frames[self.cur_frame_idx].scrollbar_pos
                )
                self.main_window.searchField.setText(
                    self.nav_frames[self.cur_frame_idx].search_text or ""
                )
                self.main_window.pagination.update_buttons(
                    self.nav_frames[self.cur_frame_idx].page_count,
                    self.nav_frames[self.cur_frame_idx].page_index,
                    emit=False,
                )

    def refresh_frame(
        self,
        frame_content: Frame,
        page_index: int = 0,
        page_count: int = 0,
    ):
        """
        Refreshes the current navigation contents without altering the
        navigation stack order.
        """
        if self.nav_frames:
            self.nav_frames[self.cur_frame_idx] = NavigationState(
                contents=frame_content,
                scrollbar_pos=0,
                page_index=self.nav_frames[self.cur_frame_idx].page_index,
                page_count=self.nav_frames[self.cur_frame_idx].page_count,
                search_text=self.main_window.searchField.text(),
            )
        else:
            self.nav_forward(
                frame_content=frame_content,
                page_index=page_index,
                page_count=page_count,
            )
        self.update_thumbs()

    def purge_item_from_navigation(self, search_result: SearchResult):
        for i, frame in enumerate(self.nav_frames, start=0):
            while search_result in frame.contents:
                logging.info(f"Removing {search_result.id} from nav stack frame {i}")
                frame.contents.remove(search_result)

        for i, key in enumerate(self.frame_dict.keys(), start=0):
            for frame in self.frame_dict[key]:
                while search_result in frame:
                    logging.info(
                        f"Removing {search_result.id} from frame dict item {i}"
                    )
                    frame.remove(search_result)

        while search_result in self.selected:
            logging.info(f"Removing {id} from frame selected")
            self.selected.remove(search_result)

    def _init_thumb_grid(self):
        layout = FlowLayout()
        layout.setGridEfficiency(True)
        layout.setSpacing(min(self.thumb_size // 10, 12))

        for _ in range(0, self.max_results):
            item_thumb = ItemThumb(
                search_result=None,
                library=self.lib,
                preview_panel=self.preview_panel,
                thumb_size=(self.thumb_size, self.thumb_size),
            )
            layout.addWidget(item_thumb)
            self.item_thumbs.append(item_thumb)

        self.flow_container: QWidget = QWidget()
        self.flow_container.setObjectName("flowContainer")
        self.flow_container.setLayout(layout)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sa: QScrollArea = self.main_window.scrollArea
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setWidgetResizable(True)
        sa.setWidget(self.flow_container)

    def select_item(self, search_result: SearchResult, append: bool, bridge: bool):
        """Selects one or more items in the Thumbnail Grid."""
        if append:
            if search_result not in self.selected:
                self.selected.append(search_result)
                for item_thumb in self.item_thumbs:
                    if item_thumb.search_result == search_result:
                        item_thumb.thumb_button.set_selected(True)
            else:
                self.selected.remove(search_result)
                for item_thumb in self.item_thumbs:
                    if item_thumb.search_result == search_result:
                        item_thumb.thumb_button.set_selected(False)

        elif bridge and self.selected:
            logging.info(f"Last Selected: {self.selected[-1]}")
            contents = self.nav_frames[self.cur_frame_idx].contents

            last_index = contents.index(self.selected[-1])
            current_index = contents.index(search_result)

            index_range = contents[
                min(last_index, current_index) : max(last_index, current_index) + 1
            ]

            if last_index < current_index:
                index_range.reverse()

            for search_result in index_range:
                if search_result not in self.selected:
                    self.selected.append(search_result)

            for item_thumb in self.item_thumbs:
                if item_thumb.search_result in self.selected:
                    item_thumb.thumb_button.set_selected(True)
                else:
                    item_thumb.thumb_button.set_selected(False)
        else:
            self.selected.clear()
            self.selected.append(search_result)
            for item_thumb in self.item_thumbs:
                if item_thumb.search_result == search_result:
                    item_thumb.thumb_button.set_selected(True)
                else:
                    item_thumb.thumb_button.set_selected(False)

        # NOTE: By using the preview panel's "set_tags_updated_slot" method,
        # only the last of multiple identical item selections are connected.
        # If attaching the slot to multiple duplicate selections is needed,
        # just bypass the method and manually disconnect and connect the slots.
        if len(self.selected) == 1:
            for item_thumb in self.item_thumbs:
                if item_thumb.search_result == search_result:
                    self.preview_panel.set_tags_updated_slot(item_thumb.update_badges)
                    break

        self.set_macro_menu_viability()
        self.preview_panel.update_widgets()

    def set_macro_menu_viability(self):
        number_of_entries_selected = len(
            [
                selected.id
                for selected in self.selected
                if isinstance(selected, EntrySearchResult)
            ]
        )

        if number_of_entries_selected == 0:
            self.autofill_action.setDisabled(True)
            self.sort_fields_action.setDisabled(True)
        else:
            self.autofill_action.setDisabled(False)
            self.sort_fields_action.setDisabled(False)

    def update_thumbs(self):
        """Updates search thumbnails."""
        if self.lib.root_path is None:
            return

        with self.thumb_job_queue.mutex:
            # Cancels all thumb jobs waiting to be started
            self.thumb_job_queue.queue.clear()
            self.thumb_job_queue.all_tasks_done.notify_all()
            self.thumb_job_queue.not_full.notify_all()
            # Stops in-progress jobs from finishing
            ItemThumb.update_cutoff = time.time()

        ratio: float = self.main_window.devicePixelRatio()
        base_size: tuple[int, int] = (self.thumb_size, self.thumb_size)

        for i, item_thumb in enumerate(self.item_thumbs):
            if i < len(self.nav_frames[self.cur_frame_idx].contents):
                search_result = self.nav_frames[self.cur_frame_idx].contents[i]
                item_thumb.set_search_result(search_result)
                item_thumb.ignore_size = False
                self.thumb_job_queue.put(
                    (
                        item_thumb.renderer.render,
                        (sys.float_info.max, "", base_size, ratio, True, True),
                    )
                )
            else:
                item_thumb.ignore_size = True
                item_thumb.set_search_result(None)
                item_thumb.set_item_id(-1)
                item_thumb.thumb_button.set_selected(False)

        self.flow_container.layout().update()
        self.main_window.update()

        limited_thumbs = self.item_thumbs[
            : len(self.nav_frames[self.cur_frame_idx].contents)
        ]
        for i, item_thumb in enumerate(limited_thumbs):
            search_result = self.nav_frames[self.cur_frame_idx].contents[i]

            if isinstance(search_result, EntrySearchResult):
                filepath = self.lib.root_path / search_result.path

                item_thumb.set_item_id(search_result.id)
                item_thumb.search_result = search_result
                item_thumb.opener.set_filepath(str(filepath))

                item_thumb.assign_archived(search_result.archived)
                item_thumb.assign_favorite(search_result.favorited)

                # TODO: Change how this works. The click function
                # for collations a few lines down should NOT be allowed during modifier keys.

                item_thumb.update_clickable(
                    clickable=(
                        lambda checked=False,
                        search_result=search_result: self.select_item(
                            search_result=search_result,
                            append=True
                            if QGuiApplication.keyboardModifiers()
                            == Qt.KeyboardModifier.ControlModifier
                            else False,
                            bridge=True
                            if QGuiApplication.keyboardModifiers()
                            == Qt.KeyboardModifier.ShiftModifier
                            else False,
                        )
                    )
                )

            else:
                # TODO
                collation = self.lib.get_collation(
                    self.nav_frames[self.cur_frame_idx].contents[i][1]
                )
                cover_id = (
                    collation.cover_id
                    if collation.cover_id >= 0
                    else collation.e_ids_and_pages[0][0]
                )
                cover_e = self.lib.get_entry(cover_id)
                filepath = os.path.normpath(
                    f"{self.lib.root_path}/{cover_e.path}/{cover_e.filename}"
                )
                item_thumb.set_count(str(len(collation.e_ids_and_pages)))
                item_thumb.update_clickable(
                    clickable=(
                        lambda checked=False,
                        filepath=filepath,
                        entry=cover_e,
                        collation=collation: (
                            self.expand_collation(collation.e_ids_and_pages)
                        )
                    )
                )

            # Restore Selected Borders
            if search_result in self.selected:
                item_thumb.thumb_button.set_selected(True)
            else:
                item_thumb.thumb_button.set_selected(False)

            self.thumb_job_queue.put(
                (
                    item_thumb.renderer.render,
                    (time.time(), filepath, base_size, ratio, False, True),
                )
            )

    def update_badges(self):
        for item_thumb in self.item_thumbs:
            # Skip not selected
            if item_thumb.search_result not in self.selected:
                continue

            item_thumb.update_badges()

    # TODO
    def expand_collation(self, collation_entries: list[tuple[int, int]]):
        self.nav_forward([(ItemType.ENTRY, x[0]) for x in collation_entries])

    def get_frame_contents(self, index: int = 0, query: str = ""):
        return (
            [] if not self.frame_dict[query] else self.frame_dict[query][index],
            index,
            len(self.frame_dict[query]),
        )

    def filter_items(self, query: str = ""):
        if self.lib:
            self.main_window.statusbar.showMessage(
                f'Searching Library for "{query}"...'
            )
            self.main_window.statusbar.repaint()

            start_time = time.time()
            all_items = self.lib.search_library(query)

            frames: Frames = []
            for item_batch in batched(all_items, self.max_results):
                frames.append(list(item_batch))

            for i, f in enumerate(frames):
                logging.info(f"Query:{query}, Frame: {i},  Length: {len(f)}")

            self.frame_dict[query] = frames

            if self.cur_query == query:
                # self.refresh_frame(self.lib.search_library(query))
                # NOTE: Trying to refresh instead of navigating forward here
                # now creates a bug when the page counts differ on refresh.
                # If refreshing is absolutely desired, see how to update
                # page counts where they need to be updated.
                self.nav_forward(*self.get_frame_contents(0, query))
            else:
                self.nav_forward(*self.get_frame_contents(0, query))
            self.cur_query = query
            end_time = time.time()

            if query:
                self.main_window.statusbar.showMessage(
                    f'{len(all_items)} Results Found for "{query}" ({format_timespan(end_time - start_time)})'
                )
            else:
                self.main_window.statusbar.showMessage(
                    f"{len(all_items)} Results ({format_timespan(end_time - start_time)})"
                )

    def remove_recent_library(self, item_key: str):
        self.settings.beginGroup(SettingItems.LIBS_LIST)
        self.settings.remove(item_key)
        self.settings.endGroup()
        self.settings.sync()

    def update_libs_list(self, path: str | Path):
        """add library to list in SettingItems.LIBS_LIST"""
        ITEMS_LIMIT = 5
        path = Path(path)

        self.settings.beginGroup(SettingItems.LIBS_LIST)

        all_libs = {str(time.time()): str(path)}

        for item_key in self.settings.allKeys():
            item_path = str(self.settings.value(item_key))
            if Path(item_path) != path:
                all_libs[item_key] = item_path

        # sort items, most recent first
        all_libs = sorted(all_libs.items(), key=lambda item: item[0], reverse=True)

        # remove previously saved items
        self.settings.clear()

        for item_key, item_value in all_libs[:ITEMS_LIMIT]:
            self.settings.setValue(item_key, item_value)

        self.settings.endGroup()
        self.settings.sync()

    def open_library(self, path: str | Path) -> None:
        """Opens a TagStudio library."""
        if self.lib.root_path:
            self.lib.clear_internal_vars()

        self.main_window.statusbar.showMessage(f"Opening Library {path}", 3)
        opened = self.lib.open_library(path)
        if not opened:
            logging.error(f"Failed to open library at {path}")

        self.add_new_files_callback()

        self.update_libs_list(path)
        title_text = f"{self.base_title} - Library '{self.lib.root_path}'"
        self.main_window.setWindowTitle(title_text)

        self.nav_frames = []
        self.cur_frame_idx = -1
        self.cur_query = ""
        self.selected.clear()
        self.preview_panel.update_widgets()
        self.filter_items()

    def create_collage(self) -> None:
        """Generates and saves an image collage based on Library Entries."""

        run: bool = True
        keep_aspect: bool = False
        data_only_mode: bool = False
        data_tint_mode: bool = False

        self.main_window.statusbar.showMessage("Creating Library Collage...")
        self.collage_start_time = time.time()

        # mode:int = self.scr_choose_option(subtitle='Choose Collage Mode(s)',
        # 	choices=[
        # 	('Normal','Creates a standard square image collage made up of Library media files.'),
        # 	('Data Tint','Tints the collage with a color representing data about the Library Entries/files.'),
        # 	('Data Only','Ignores media files entirely and only outputs a collage of Library Entry/file data.'),
        # 	('Normal & Data Only','Creates both Normal and Data Only collages.'),
        # 	], prompt='', required=True)
        mode = 0

        if mode == 1:
            data_tint_mode = True

        if mode == 2:
            data_only_mode = True

        if mode in [0, 1, 3]:
            # keep_aspect = self.scr_choose_option(
            # 	subtitle='Choose Aspect Ratio Option',
            # 	choices=[
            # 	('Stretch to Fill','Stretches the media file to fill the entire collage square.'),
            # 	('Keep Aspect Ratio','Keeps the original media file\'s aspect ratio, filling the rest of the square with black bars.')
            # 	], prompt='', required=True)
            keep_aspect = False

        if mode in [1, 2, 3]:
            # TODO: Choose data visualization options here.
            pass

        full_thumb_size: int = 1

        if mode in [0, 1, 3]:
            # full_thumb_size = self.scr_choose_option(
            # 	subtitle='Choose Thumbnail Size',
            # 	choices=[
            # 	('Tiny (32px)',''),
            # 	('Small (64px)',''),
            # 	('Medium (128px)',''),
            # 	('Large (256px)',''),
            # 	('Extra Large (512px)','')
            # 	], prompt='', required=True)
            full_thumb_size = 0

        thumb_size: int = (
            32
            if (full_thumb_size == 0)
            else 64
            if (full_thumb_size == 1)
            else 128
            if (full_thumb_size == 2)
            else 256
            if (full_thumb_size == 3)
            else 512
            if (full_thumb_size == 4)
            else 32
        )
        thumb_size = 16

        # if len(com) > 1 and com[1] == 'keep-aspect':
        # 	keep_aspect = True
        # elif len(com) > 1 and com[1] == 'data-only':
        # 	data_only_mode = True
        # elif len(com) > 1 and com[1] == 'data-tint':
        # 	data_tint_mode = True
        grid_size = math.ceil(math.sqrt(len(self.lib.entries))) ** 2
        grid_len = math.floor(math.sqrt(grid_size))
        thumb_size = thumb_size if not data_only_mode else 1
        img_size = thumb_size * grid_len

        logging.info(
            f"Creating collage for {len(self.lib.entries)} Entries.\nGrid Size: {grid_size} ({grid_len}x{grid_len})\nIndividual Picture Size: ({thumb_size}x{thumb_size})"
        )
        if keep_aspect:
            logging.info("Keeping original aspect ratios.")
        if data_only_mode:
            logging.info("Visualizing Entry Data")

        if not data_only_mode:
            time.sleep(5)

        self.collage = Image.new("RGB", (img_size, img_size))
        i = 0
        self.completed = 0
        for x in range(0, grid_len):
            for y in range(0, grid_len):
                if i < len(self.lib.entries) and run:
                    # if i < 5 and run:

                    entry_id = self.lib.entries[i].id
                    renderer = CollageIconRenderer(self.lib)
                    renderer.rendered.connect(  # type: ignore
                        lambda image, x=x, y=y: self.collage.paste(  # type: ignore
                            image,  # type: ignore
                            (y * thumb_size, x * thumb_size),
                        )
                    )
                    renderer.done.connect(lambda: self.try_save_collage(True))
                    self.thumb_job_queue.put(
                        (
                            renderer.render,  # type: ignore
                            (
                                entry_id,
                                (thumb_size, thumb_size),
                                data_tint_mode,
                                data_only_mode,
                                keep_aspect,
                            ),
                        )
                    )
                i = i + 1

    def try_save_collage(self, increment_progress: bool):
        if increment_progress:
            self.completed += 1
        if self.completed == len(self.lib.entries):
            filename = os.path.normpath(
                f'{self.lib.library_dir}/{TS_FOLDER_NAME}/{COLLAGE_FOLDER_NAME}/collage_{dt.utcnow().strftime("%F_%T").replace(":", "")}.png'
            )
            self.collage.save(filename)
            self.collage = None

            end_time = time.time()
            self.main_window.statusbar.showMessage(
                f'Collage Saved at "{filename}" ({format_timespan(end_time - self.collage_start_time)})'
            )
            logging.info(
                f'Collage Saved at "{filename}" ({format_timespan(end_time - self.collage_start_time)})'
            )
