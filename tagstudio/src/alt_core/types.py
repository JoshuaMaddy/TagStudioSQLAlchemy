from enum import Enum
from pathlib import Path


class ItemType(Enum):
    ENTRY = 0
    COLLATION = 1
    TAG_GROUP = 2


class SettingItems(str, Enum):
    """List of setting item names."""

    START_LOAD_LAST = "start_load_last"
    LAST_LIBRARY = "last_library"
    LIBS_LIST = "libs_list"
    WINDOW_SHOW_LIBS = "window_show_libs"


class Theme(str, Enum):
    COLOR_BG = "#65000000"
    COLOR_HOVER = "#65AAAAAA"
    COLOR_PRESSED = "#65EEEEEE"


ContentItem = tuple[ItemType, int, Path]
Frame = list[ContentItem]
Frames = list[Frame]


class TagColor(Enum):
    black = "black"
    dark_gray = "dark gray"
    gray = "gray"
    light_gray = "light gray"
    white = "white"
    light_pink = "light pink"
    pink = "pink"
    red = "red"
    red_orange = "red orange"
    orange = "orange"
    yellow_orange = "yellow orange"
    yellow = "yellow"
    lime = "lime"
    light_green = "light green"
    mint = "mint"
    green = "green"
    teal = "teal"
    cyan = "cyan"
    light_blue = "light blue"
    blue = "blue"
    blue_violet = "blue violet"
    violet = "violet"
    purple = "purple"
    lavender = "lavender"
    berry = "berry"
    magenta = "magenta"
    salmon = "salmon"
    auburn = "auburn"
    dark_brown = "dark brown"
    brown = "brown"
    light_brown = "light brown"
    blonde = "blonde"
    peach = "peach"
    warm_gray = "warm gray"
    cool_gray = "cool gray"
    olive = "olive"