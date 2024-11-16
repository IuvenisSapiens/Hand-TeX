import handtex.utils as ut
import re
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

import handtex.data
import handtex.structures as st
from handtex import __program__, __version__
from handtex.data import color_themes
from handtex.data import symbol_metadata


def test_similar_lists_disjunct() -> None:
    """
    Test that the symbol lists are disjunct.
    """
    with resources.path(symbol_metadata, "") as metadata_dir:
        metadata_dir = Path(metadata_dir)
    files = list(metadata_dir.glob("similar*"))

    # Check that each file is consistent on it's own.
    for file in files:
        line_symbols: list[set[str]]
        line_symbols = []

        with file.open("r") as f:
            lines = f.readlines()
        for line in lines:
            symbols = line.strip().split()
            line_symbol_set = set()
            for s in symbols:
                assert (
                    s not in line_symbol_set
                ), f"Symbol {s} is listed twice in {file}, line {line}"
                line_symbol_set.add(s)
            assert line_symbol_set not in line_symbols, f"Line {line} is listed twice in {file}"
            line_symbols.append(line_symbol_set)

        # Check that no two lines are a subset of each other.
        for i, line1 in enumerate(line_symbols, 1):
            for j, line2 in enumerate(line_symbols, 1):
                if i == j:
                    continue
                assert not line1.issubset(line2), f"Line {i} is a subset of line {j} in {file}"

        # Check that all lines are disjunct.
        for i, line1 in enumerate(line_symbols, 1):
            for j, line2 in enumerate(line_symbols, 1):
                if i == j:
                    continue
                assert not line1 & line2, f"Line {i} and line {j} share symbols in {file}"

    # There cannot be the same key listed twice in the file.
    global_keys = set()
    for file in files:
        # Just parse out all the keys with a regex.
        # A key is a string of 1 or more characters, no whitespace.
        keys = list(re.findall(r"\S+", file.read_text()))
        key_set = set(keys)
        for key in key_set:
            keys.remove(key)
        assert not keys, f"File {file} contains duplicate keys: {keys}"

        # The keys in this file must not be in the global set.
        intersection = global_keys & key_set
        assert (
            not intersection
        ), f"File {file} contains keys already in another file: {intersection}"
        global_keys |= key_set
