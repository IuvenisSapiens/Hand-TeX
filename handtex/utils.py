import difflib
import os
import platform
import shutil
import sys
from importlib import resources
from io import StringIO
from pathlib import Path
from typing import get_type_hints, Generic, TypeVar, Optional

import PySide6
import PySide6.QtCore as Qc
import PySide6.QtGui as Qg
import PySide6.QtWidgets as Qw
import psutil
from loguru import logger
from xdg import XDG_CONFIG_HOME, XDG_CACHE_HOME

from handtex import __program__, __version__
from handtex.data import color_themes


T = TypeVar("T")


class Shared(Generic[T]):
    def __init__(self, initial_value: Optional[T] = None) -> None:
        self._container = {"data": initial_value}

    def get(self) -> Optional[T]:
        return self._container["data"]

    def set(self, value: T) -> None:
        self._container["data"] = value

    def is_none(self) -> bool:
        return self._container["data"] is None


# Logging session markers.
STARTUP_MESSAGE = "---- Starting up ----"
SHUTDOWN_MESSAGE = "---- Shutting down ----"


def running_in_flatpak() -> bool:
    return Path("/.flatpak-info").exists()


def collect_system_info(callers_file: str) -> str:
    buffer = StringIO()
    buffer.write("\n" + STARTUP_MESSAGE)
    buffer.write("\n- Program Information -\n")
    buffer.write(f"Program: {__program__} {__version__}\n")
    buffer.write(f"Executing from: {callers_file}\n")
    buffer.write(f"Log file: {get_log_path()}\n")
    buffer.write(f"Config file: {get_config_path()}\n")
    buffer.write(f"Cache directory: {get_cache_path()}\n")
    buffer.write("- System Information -\n")
    buffer.write(f"Operating System: {platform.system()} {platform.release()}\n")
    if platform.system() == "Linux":
        buffer.write(f"Desktop Environment: {os.getenv('XDG_CURRENT_DESKTOP', 'unknown')}\n")
    if running_in_flatpak():
        buffer.write("Sandbox: Running in Flatpak\n")
    buffer.write(f"Machine: {platform.machine()}\n")
    buffer.write(f"Python Version: {sys.version}\n")
    buffer.write(f"PySide (Qt) Version: {PySide6.__version__}\n")
    buffer.write(f"Available Qt Themes: {', '.join(Qw.QStyleFactory.keys())}\n")
    current_app_theme = Qw.QApplication.style()
    current_app_theme_name = (
        current_app_theme.objectName() if current_app_theme else "System Default"
    )
    buffer.write(f"Current Qt Theme: {current_app_theme_name}\n")
    icon_theme_name = Qg.QIcon.themeName()
    icon_theme_name = icon_theme_name if icon_theme_name else "System Default"
    buffer.write(f"Current Icon Theme: {icon_theme_name}\n")
    buffer.write(
        f"Available Color Themes: {', '.join(map(lambda a: a[1], get_available_themes()))}\n"
    )
    buffer.write(f"System locale: {Qc.QLocale.system().name()}\n")
    buffer.write(f"CPU Cores: {os.cpu_count()}\n")
    buffer.write(f"Memory: {psutil.virtual_memory().total / 1024 ** 3:.2f} GiB\n")
    buffer.write(f"Swap: {psutil.swap_memory().total / 1024 ** 3:.2f} GiB\n")

    return buffer.getvalue()


def get_config_path() -> Path:
    """
    Get the path to the configuration file for both Linux and Windows.
    """
    xdg_path = os.getenv("XDG_CONFIG_HOME") or Path.home() / ".config"

    if platform.system() == "Linux":
        path = Path(XDG_CONFIG_HOME, __program__, __program__ + "rc")
    elif platform.system() == "Windows":
        path = Path(
            xdg_path if "XDG_CONFIG_HOME" in os.environ else os.getenv("APPDATA"),
            __program__,
            __program__ + "config.ini",
        )
    elif platform.system() == "Darwin":
        path = Path(
            (
                xdg_path
                if "XDG_CONFIG_HOME" in os.environ
                else (Path.home() / "Library" / "Application Support")
            ),
            __program__,
            __program__ + "config.ini",
        )
    else:  # ???
        raise NotImplementedError("Your OS is currently not supported.")

    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_path() -> Path:
    """
    Get the default suggested path to the cache directory for both Linux and Windows.
    """
    xdg_path = os.getenv("XDG_CACHE_HOME") or Path.home() / ".cache"

    if platform.system() == "Linux":
        path = Path(XDG_CACHE_HOME, __program__)
    elif platform.system() == "Windows":
        path = Path(
            xdg_path if "XDG_CACHE_HOME" in os.environ else os.getenv("APPDATA"),
            __program__,
            "cache",
        )
    elif platform.system() == "Darwin":
        path = Path(
            xdg_path if "XDG_CACHE_HOME" in os.environ else (Path.home() / "Library" / "Caches"),
            __program__,
        )
    else:  # ???
        raise NotImplementedError("Your OS is currently not supported.")

    path.mkdir(parents=True, exist_ok=True)
    return path


def get_log_path() -> Path:
    """
    Get the path to the log file.
    Use the cache directory for this.
    """
    return get_cache_path() / f"{__program__}.log"


def get_available_themes() -> list[tuple[str, str]]:
    """
    Check the data/color_themes directory for available themes.
    The theme name is the plain file name. The display name is either defined in the
    theme file under section General, key name.
    If not defined, the display name is the theme name but capitalized and
    with spaces instead of underscores.

    Note: The implicit system theme is not included in the list.

    :return: A list of available theme names with their display names.
    """
    # Simply discover all files in the themes folder.
    themes = []
    with resources.path(color_themes, "") as theme_dir:
        theme_dir = Path(theme_dir)
    for theme_file in theme_dir.iterdir():
        # Skip dirs and empty files.
        if theme_file.is_dir() or theme_file.stat().st_size == 0:
            continue
        theme_name = theme_file.stem
        content = theme_file.read_text()
        display_name = theme_name.replace("_", " ").capitalize()
        in_general_section = False
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("[General]"):
                in_general_section = True
            elif line.startswith("[") and line.endswith("]"):
                if in_general_section:
                    # We found general, but came across the next section now.
                    break
                in_general_section = False
            elif "=" in line:
                key, value = map(str.strip, line.split("=", 1))
                if key == "Name":
                    display_name = value
                    break
        themes.append((theme_name, display_name))

    return themes


def closest_match(word: str, choices: list[str]) -> str | None:
    """
    Return the closest match for the given word in the list of choices.
    If no good match is found, return None.
    """
    if word in choices:
        return word
    else:
        # Find the closest match using difflib:
        closest = difflib.get_close_matches(word, choices, 1, 0.5)  # 0.6 is the default threshold
        if closest:
            return str(closest[0])
        else:
            return None


def f_plural(value, singular: str, plural: str = "") -> str:
    """
    Selects which form to use based on the value.

    :param value: Value to check.
    :param singular: Singular form.
    :param plural: (Optional) Plural form. If not given, the singular form is used with an 's' appended.
    :return: The appropriate form.
    """
    if not plural:
        plural = singular + "s"
    return singular if value == 1 else plural


def f_time(seconds: int) -> str:
    """
    Format a time in seconds to a human readable string.
    Return a format like:
    1 second
    2 minutes 3 seconds
    4 hours 5 minutes
    """
    if seconds < 60:
        return f"{seconds} {f_plural(seconds, 'second')}"
    elif seconds < 60 * 60:
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes} {f_plural(minutes, 'minute')} {seconds} {f_plural(seconds, 'second')}"
    else:
        hours = seconds // (60 * 60)
        minutes = (seconds % (60 * 60)) // 60
        return (
            f"{hours} {f_plural(hours, 'hour')} "
            f"{minutes} {f_plural(minutes, 'minute')}"
            f"   [You're batshit insane!]"
        )


def open_file(path: Path) -> None:
    """
    Open any given file with the default application.
    """
    logger.info(f"Opening file {path}")
    try:
        # Use Qt to open the file, so that it works on all platforms.
        Qg.QDesktopServices.openUrl(Qc.QUrl.fromLocalFile(str(path)))
    except Exception as e:
        logger.exception(e)


def ensure_unique_file_path(file_path: Path) -> Path:
    """
    Ensure that the file path is unique.
    If the file already exists, append a number to the file name,
    incrementing it until a unique file path is found.
    """
    counter = 1
    output_file_path = file_path
    while output_file_path.exists():
        output_file_path = file_path.parent / (
            file_path.stem + "_" + str(counter) + file_path.suffix
        )
        counter += 1
    return output_file_path


def backup_file(path: Path, extension: str = ".backup") -> Path:
    """
    Create a backup of the file by copying it to the same location with the given extension.
    """
    backup_path = path.with_suffix(path.suffix + extension)
    backup_path = ensure_unique_file_path(backup_path)
    logger.info(f"Backing up file {path} to {backup_path}")
    shutil.copy(path, backup_path)
    return backup_path


class RecoverableParseException(Exception):
    """
    This serves to wrap any exceptions that occur during parsing,
    so that additional info about the file can be included.
    These exceptions could be recovered from.
    """

    pass


class ParseError(Exception):
    """
    This serves to wrap any errors that occur during parsing,
    so that additional info about the file can be included.
    Errors imply a failure to parse major parts of the file.
    """

    pass


class CriticalParseError(Exception):
    """
    This serves to wrap any critical errors that occur during parsing,
    so that additional info about the file can be included.
    A critical error implies a failure to parse the file at all.
    """

    pass


def load_dict_to_attrs_safely(
    dataclass: object,
    data: dict,
    *,
    skip_attrs: list[str] | None = None,
    include_until_base: type | list[type] | None = None,
) -> list[RecoverableParseException]:
    """
    Load a dictionary into an attrs class while ensuring types are correct.
    Any type issues are logged and returned as a list of exceptions.
    If no exceptions are returned, the loading was successful.
    In the worst case, the object is simply left unchanged.
    When you have a dataclass that inherits from another one, type annotations won't be inherited,
    so set include_until_base to the base class to include all attributes up to (and including)
    that class (multiple inheritance is supported).

    :param dataclass: The dataclass to load the dictionary into.
    :param data: The dictionary to load.
    :param skip_attrs: [Optional] A list of attributes to skip.
    :param include_until_base: [Optional] Include attributes until this base class.
    :return: A list of exceptions that occurred during loading.
    """
    recoverable_exceptions: list[RecoverableParseException] = []
    type_info = get_type_hints(dataclass)
    # Gather type hints from base classes if requested.
    if include_until_base:
        if not isinstance(include_until_base, list):
            include_until_base = [include_until_base]
        base_classes = list(type(dataclass).__bases__)
        while base_classes:
            base_class = base_classes.pop(0)
            type_info.update(get_type_hints(base_class))
            if base_class not in include_until_base:
                base_classes.extend(list(base_class.__bases__))

    for attribute in type_info:
        if skip_attrs and attribute in skip_attrs:
            continue

        if attribute in data:
            # Attempt to coerce the type to the correct one.
            value = data[attribute]
            expected_type = type_info[attribute]
            try:
                setattr(dataclass, attribute, expected_type(value))
            except Exception as e:
                logger.exception(f"Failed to cast attribute {attribute} to the correct type.")
                recoverable_exceptions.append(
                    RecoverableParseException(
                        f"{type(e).__name__}: Failed to cast attribute {attribute} to the correct type: {e}"
                    )
                )

    return recoverable_exceptions
