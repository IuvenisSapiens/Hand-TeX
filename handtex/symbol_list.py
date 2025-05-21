import re
import time
from enum import IntEnum

import PySide6.QtCore as Qc
import PySide6.QtGui as Qg
import PySide6.QtSvg as Qs
import PySide6.QtWidgets as Qw
from PySide6.QtCore import Qt
from loguru import logger
from natsort import natsorted

import handtex.state_saver as ss
import handtex.structures as st
import handtex.utils as ut
import handtex.symbol_relations as sr
import handtex.gui_utils as gu
import handtex.worker_thread as wt
from handtex.ui_generated_files.ui_SymbolList import Ui_SymbolList


class SearchField(IntEnum):
    COMMAND = 0
    ID = 1


class SearchMode(IntEnum):
    IGNORECASE = 0
    CASE_SENSITIVE = 1
    REGEX = 2


class GroupBy(IntEnum):
    NO_GROUPING = 0
    PACKAGE = 1
    SIMILARITY = 2
    SYMMETRY = 3
    NEGATION = 4
    INSIDE = 5


class Symmetry(IntEnum):
    IGNORE = 0
    SYMMETRIC = 1
    ASYMMETRIC = 2


class CommandMode(IntEnum):
    BOTH = 0
    MATH = 1
    TEXT = 2


class Sorting(IntEnum):
    NONE = 0
    ASCENDING = 1
    DESCENDING = 2


class SymbolList(Qw.QWidget, Ui_SymbolList):

    symbols: dict[str, st.Symbol]
    last_shown_symbol: str | None
    symbol_data: sr.SymbolData
    icon_size: int
    pixmap_cache: dict[str, Qg.QPixmap]
    current_symbol_keys: list[str | None]
    disable_filtering: bool  # Used to ignore filter signals while resetting the filters.
    search_pool: list[str | None]  # All symbol keys, used for searching.

    symbol_queue: Qc.QThreadPool
    loaded: bool

    state_saver: ss.StateSaver

    def __init__(
        self,
        symbol_data: sr.SymbolData,
        parent=None,
    ):
        super(SymbolList, self).__init__(parent)
        self.setupUi(self)
        self.symbol_data = symbol_data
        self.last_show_symbol = symbol_data.all_keys[0]
        self.disable_filtering = False
        self.search_pool = symbol_data.all_keys
        self.setWindowIcon(gu.load_custom_icon("logo"))

        self.icon_size = 100
        self.listWidget.setIconSize(Qc.QSize(self.icon_size, self.icon_size))

        self.pixmap_cache = {}
        self.current_symbol_keys = self.search_pool

        self.symbol_queue = Qc.QThreadPool()
        self.symbol_queue.setMaxThreadCount(1)

        self.loaded = False
        self.preload_symbols()

        self.listWidget.currentItemChanged.connect(self.on_symbol_selected)
        self.listWidget.setCurrentRow(0)

        self.comboBox_search_field.currentIndexChanged.connect(self.listWidget.clearSelection)
        self.comboBox_search_field.currentIndexChanged.connect(self.search_symbols)
        self.lineEdit_search.textEdited.connect(self.search_symbols)
        self.comboBox_sort.currentIndexChanged.connect(self.search_symbols)

        # Init UI.
        font = self.label_command.font()
        font.setPointSize(2 * font.pointSize())
        font.setBold(True)
        self.label_command.setFont(font)
        # Make the right splitter side 250px wide.
        self.splitter.setSizes([self.width() - 320, 320])
        self.listWidget.verticalScrollBar().setSingleStep(40)

        self.pushButton_filter.clicked.connect(self.toggle_filter_menu)
        self.init_filter_drawer()
        self.clear_filters()

        self.state_saver = ss.StateSaver("symbol_list")
        self.init_state_saver()
        self.state_saver.restore()

        # Focus search bar with Ctrl+F.
        shortcut = Qg.QShortcut(Qg.QKeySequence("Ctrl+F"), self)
        shortcut.activated.connect(self.focus_line_edit)

    def show(self):
        super().show()
        # Focus the search bar when the window is shown.
        self.focus_line_edit()

    def focus_line_edit(self):
        """Sets focus to the QLineEdit"""
        self.lineEdit_search.setFocus()
        self.lineEdit_search.selectAll()  # Optional: selects all text

    def init_state_saver(self) -> None:
        """
        Load the state from the state saver.
        """
        self.state_saver.register(
            self,
            self.splitter,
            self.comboBox_search_field,
        )

    def closeEvent(self, event) -> None:
        self.state_saver.save()
        event.accept()

    def toggle_filter_menu(self) -> None:
        if self.widget_filters.isVisible():
            self.widget_filters.hide()
            self.pushButton_filter.setChecked(False)
        else:
            self.widget_filters.show()
            self.pushButton_filter.setChecked(True)

    def init_filter_drawer(self) -> None:
        self.widget_filters.hide()
        # Init the packages and encodings lists.
        package_menu = Qw.QMenu(self.pushButton_packages)
        encoding_menu = Qw.QMenu(self.pushButton_encodings)
        for package in self.symbol_data.packages:
            check_box_action = Qw.QWidgetAction(package_menu)
            check_box = Qw.QCheckBox(package)
            check_box_action.setDefaultWidget(check_box)
            package_menu.addAction(check_box_action)
        for encoding in self.symbol_data.encodings:
            check_box_action = Qw.QWidgetAction(encoding_menu)
            check_box = Qw.QCheckBox(encoding)
            check_box_action.setDefaultWidget(check_box)
            encoding_menu.addAction(check_box_action)
        self.pushButton_packages.setMenu(package_menu)
        self.pushButton_encodings.setMenu(encoding_menu)
        # Connect the checkboxes to the filter function.
        for action in package_menu.actions():
            action.defaultWidget().stateChanged.connect(self.update_filters)
        for action in encoding_menu.actions():
            action.defaultWidget().stateChanged.connect(self.update_filters)
        # Connect all other comboboxes to the filter function.
        self.comboBox_mode.currentIndexChanged.connect(self.update_filters)
        self.comboBox_symmetry.currentIndexChanged.connect(self.update_filters)
        self.comboBox_grouping.currentIndexChanged.connect(self.update_filters)
        self.pushButton_clear_filters.clicked.connect(self.clear_filters)
        self.spinBox_group_min_size.valueChanged.connect(self.update_filters)
        self.spinBox_group_max_size.valueChanged.connect(self.update_filters)
        # This one doesn't affect the underlying search pool.
        self.comboBox_case.currentIndexChanged.connect(self.search_symbols)

    def update_filters(self) -> None:
        if self.disable_filtering:
            return
        self.pushButton_clear_filters.show()
        # Update the search pool based on the filters.
        group_by = GroupBy(self.comboBox_grouping.currentIndex())
        symmetry = Symmetry(self.comboBox_symmetry.currentIndex())
        command_mode = CommandMode(self.comboBox_mode.currentIndex())
        packages = [
            action.defaultWidget().text()
            for action in self.pushButton_packages.menu().actions()
            if action.defaultWidget().isChecked()
        ]
        encodings = [
            action.defaultWidget().text()
            for action in self.pushButton_encodings.menu().actions()
            if action.defaultWidget().isChecked()
        ]

        if group_by == GroupBy.NO_GROUPING:
            self.search_pool = self.symbol_data.all_keys
        else:
            if group_by == GroupBy.PACKAGE:
                grouping = self.symbol_data.symbols_grouped_by_package
            elif group_by == GroupBy.SIMILARITY:
                grouping = self.symbol_data.symbols_grouped_by_similarity
            elif group_by == GroupBy.SYMMETRY:
                grouping = self.symbol_data.symbols_grouped_by_transitive_symmetry
            elif group_by == GroupBy.NEGATION:
                grouping = self.symbol_data.symbols_grouped_by_negation
            elif group_by == GroupBy.INSIDE:
                grouping = self.symbol_data.symbols_grouped_by_inside
            else:
                raise ValueError(f"Invalid grouping: {group_by}")
            grouping = [
                group
                for group in grouping
                if self.spinBox_group_max_size.value()
                >= len(group)
                >= self.spinBox_group_min_size.value()
            ]

            self.search_pool = []
            if grouping:
                for group in grouping[:-1]:
                    self.search_pool.extend(group)
                    self.search_pool.append(None)
                self.search_pool.extend(grouping[-1])

        # Apply the filters.
        if command_mode == CommandMode.MATH:
            self.search_pool = filter(
                lambda key: key is None or self.symbol_data[key].mathmode, self.search_pool
            )
        elif command_mode == CommandMode.TEXT:
            self.search_pool = filter(
                lambda key: key is None or self.symbol_data[key].textmode, self.search_pool
            )

        if symmetry == Symmetry.SYMMETRIC:
            self.search_pool = filter(
                lambda key: key is None or key not in self.symbol_data.asymmetric_symbols,
                self.search_pool,
            )
        elif symmetry == Symmetry.ASYMMETRIC:
            self.search_pool = filter(
                lambda key: key is None or key in self.symbol_data.asymmetric_symbols,
                self.search_pool,
            )

        self.search_pool = filter(
            lambda key: key is None
            or self.symbol_data[key].package in packages
            and self.symbol_data[key].fontenc in encodings,
            self.search_pool,
        )

        # Resolve the filter generator.
        self.search_pool = list(self.search_pool)
        self.search_symbols()

    def clear_filters(self) -> None:
        self.disable_filtering = True
        for action in self.pushButton_packages.menu().actions():
            action.defaultWidget().setChecked(True)
        for action in self.pushButton_encodings.menu().actions():
            action.defaultWidget().setChecked(True)
        self.comboBox_case.setCurrentIndex(0)
        self.comboBox_mode.setCurrentIndex(0)
        self.comboBox_symmetry.setCurrentIndex(0)
        self.comboBox_grouping.setCurrentIndex(0)
        self.lineEdit_search.setRegexEnabled(False)
        self.disable_filtering = False
        self.update_filters()
        self.pushButton_clear_filters.hide()

    def on_theme_change(self) -> None:
        # Nuke the cache and redraw.
        self.pixmap_cache = {}
        self.show_symbols()
        self.show_symbol_details(None)

    def search_symbols(self) -> None:
        """
        Check the mode and current search text, then update the list of symbols.
        """
        search_text = self.lineEdit_search.text().strip()
        search_field = SearchField(self.comboBox_search_field.currentIndex())
        search_mode = SearchMode(self.comboBox_case.currentIndex())
        sorting = Sorting(self.comboBox_sort.currentIndex())

        # Grouped pools use None as a separator. We want to ignore consecutive separators.
        last_was_separator = False
        regex = None
        if search_mode == SearchMode.REGEX:
            try:
                regex = re.compile(search_text)
            except re.error:
                # Use a contradicting regex to avoid any matches.
                regex = re.compile(r"\b\B")
        self.lineEdit_search.setRegexEnabled(search_mode == SearchMode.REGEX)

        def filter_separators(key: str | None) -> bool:
            nonlocal last_was_separator
            if key is None:
                if last_was_separator:
                    return False
                last_was_separator = True
                return True
            last_was_separator = False
            return True

        def search_filter(check: str, match_in: str) -> bool:
            if not match_in:
                return True
            nonlocal regex
            if search_mode == SearchMode.IGNORECASE:
                return match_in.lower() in check.lower()
            elif search_mode == SearchMode.CASE_SENSITIVE:
                return match_in in check
            elif search_mode == SearchMode.REGEX:
                return bool(regex.search(check))
            else:
                raise ValueError(f"Invalid search mode: {search_mode}")

        def get_search_item(key: str) -> str:
            if search_field == SearchField.COMMAND:
                return self.symbol_data[key].command
            elif search_field == SearchField.ID:
                return key
            else:
                raise ValueError(f"Invalid search field: {search_field}")

        # Do the filtering.
        self.current_symbol_keys = [
            key
            for key in self.search_pool
            if (key is None) or search_filter(get_search_item(key), search_text)
        ]

        # If sorting, remove group separators. Otherwise make sure we don't have consecutive separators.
        if sorting != Sorting.NONE:
            self.current_symbol_keys = filter(lambda key: key is not None, self.current_symbol_keys)
        else:
            self.current_symbol_keys = list(filter(filter_separators, self.current_symbol_keys))
            # Remove leading and trailing separators.
            if self.current_symbol_keys and self.current_symbol_keys[0] is None:
                self.current_symbol_keys.pop(0)
            if self.current_symbol_keys and self.current_symbol_keys[-1] is None:
                self.current_symbol_keys.pop(-1)

        # Sort the search pool. Watch for case sensitivity.
        def get_sort_item(key: str) -> str:
            if search_mode == SearchMode.IGNORECASE:
                return get_search_item(key).lower()
            else:
                return get_search_item(key)

        if sorting == Sorting.ASCENDING:
            self.current_symbol_keys = natsorted(self.current_symbol_keys, key=get_sort_item)
        elif sorting == Sorting.DESCENDING:
            self.current_symbol_keys = natsorted(
                self.current_symbol_keys, reverse=True, key=get_sort_item
            )

        self.show_symbols()

    def on_symbol_selected(self, *_) -> None:
        current_index = self.listWidget.currentRow()
        if current_index < 0:
            return
        if self.listWidget.count() == 0:
            return
        if current_index >= len(self.current_symbol_keys):
            return

        symbol_key = self.current_symbol_keys[current_index]
        if symbol_key is None:
            return
        self.show_symbol_details(symbol_key)

    def preload_symbols(self) -> None:
        worker = wt.Worker(self.show_symbols, True, no_progress_callback=True)
        worker.signals.error.connect(self.show_symbol_errors)
        worker.signals.result.connect(self.preload_done)
        self.symbol_queue.start(worker)

    def preload_done(self) -> None:
        self.loaded = True
        self.show_symbol_details(None)

    def show_symbol_errors(self, error: wt.WorkerError) -> None:
        gu.show_exception(
            self,
            self.tr("Symbol List Loading Failed"),
            self.tr("Failed to load the symbol list."),
            error,
        )

    def show_symbols(self, preloading: bool = False) -> None:
        if not self.loaded and not preloading:
            return
        if preloading:
            logger.info("Preloading symbols.")
        self.listWidget.clear()
        separator_pixmap = Qg.QPixmap(self.icon_size, self.icon_size)
        separator_pixmap.fill(Qt.transparent)
        # Draw a vertical line in text color.
        painter = Qg.QPainter(separator_pixmap)
        painter.setPen(self.palette().color(Qg.QPalette.Text))
        painter.drawLine(
            separator_pixmap.width() // 2,
            int(separator_pixmap.height() * 0.2),
            separator_pixmap.width() // 2,
            int(separator_pixmap.height() * 0.8),
        )
        painter.end()
        for key in self.current_symbol_keys:
            # print(key)
            if key is None:
                # Add a spacer item to force a new line (like a line break).
                spacer_item = Qw.QListWidgetItem(separator_pixmap, " ")
                spacer_item.setFlags(spacer_item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
                # Set a size hint wide enough to take up the rest of the row.
                # Adjust width value based on how wide your items are.
                self.listWidget.addItem(spacer_item)
                continue
            label = self.symbol_data[key].command
            pixmap = self.get_symbol_pixmap(key)

            item = Qw.QListWidgetItem(pixmap, label)
            self.listWidget.addItem(item)

        self.label_count.setText(
            str(sum(1 for _ in (filter(lambda k: k is not None, self.current_symbol_keys))))
        )

    def show_symbol_details(self, symbol_key: str | None):
        if not self.loaded:
            return
        if symbol_key is None:
            symbol_key = self.last_show_symbol
        else:
            self.last_show_symbol = symbol_key
        if symbol_key is None:
            return
        symbol = self.symbol_data[symbol_key]
        self.label_id.setText(symbol.key)
        self.label_command.setText(symbol.command)
        self.label_mode.setText(symbol.mode_str())
        self.label_xelatex_required.setVisible(not symbol.pdflatex)
        self.label_xelatex_required_label.setVisible(not symbol.pdflatex)
        suffix = ""
        if symbol.package_is_default():
            suffix = " (default)"
        self.label_package.setText(symbol.package + suffix)
        suffix = ""
        if symbol.fontenc_is_default():
            suffix = " (default)"
        self.label_fontenc.setText(symbol.fontenc + suffix)
        self.label_self_symmetry.setText(
            "Yes" if self.symbol_data.has_self_symmetry(symbol_key) else "No"
        )

        if self.symbol_data.has_other_symmetry(symbol_key):
            self.label_other_symmetry.setText(
                ", ".join(
                    key
                    for key in self.symbol_data.get_symmetry_group(symbol_key)
                    if key != symbol_key
                )
            )
        else:
            self.label_other_symmetry.setText("")

        if self.symbol_data.has_negation(symbol_key):
            self.label_negation.setText(
                ", ".join(key for key in self.symbol_data.get_negation_of(symbol_key))
            )
        else:
            self.label_negation.setText("")

        match self.symbol_data.get_inside_of_shape(symbol_key):
            case st.Inside.Circle:
                self.label_inside_shape.setText("Circle")
            case st.Inside.Square:
                self.label_inside_shape.setText("Square")
            case st.Inside.Triangle:
                self.label_inside_shape.setText("Triangle")
            case None:
                self.label_inside_shape.setText("")

        if len(self.symbol_data.get_similarity_group(symbol_key)) > 1:
            self.label_similar.setText(
                ", ".join(
                    key
                    for key in self.symbol_data.get_similarity_group(symbol_key)
                    if key != symbol_key
                )
            )
        else:
            self.label_similar.setText("")

        hex_color = self.palette().color(Qg.QPalette.Text).name()
        self.widget_symbol_view.load(ut.load_symbol_svg(symbol, hex_color))
        self.widget_symbol_view.renderer().setAspectRatioMode(Qc.Qt.KeepAspectRatio)
        self.widget_symbol_view.setFixedSize(200, 200)

    def get_symbol_pixmap(self, symbol_key: str) -> Qg.QPixmap:
        if symbol_key in self.pixmap_cache:
            return self.pixmap_cache[symbol_key]
        hex_color = self.palette().color(Qg.QPalette.Text).name()
        svg_xml = ut.load_symbol_svg(self.symbol_data[symbol_key], hex_color)
        svg_renderer = Qs.QSvgRenderer()
        svg_renderer.load(svg_xml)
        svg_renderer.setAspectRatioMode(Qt.KeepAspectRatio)
        pixmap = Qg.QPixmap(self.icon_size, self.icon_size)
        pixmap.fill(Qt.transparent)
        svg_renderer.render(Qg.QPainter(pixmap))
        self.pixmap_cache[symbol_key] = pixmap
        return pixmap
