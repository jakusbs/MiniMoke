"""
File:         ui/motors_tab.py
Author:       Benedikt Moneke ?
Website:      https://pymeasure.readthedocs.io/en/latest/

Description:
    This file is from the PyMeasure library. It is not fully commented.
    The only modifications regards the handling of multiple procedures
    and the possibility to queue the same experiment multiple times.
    This is done is the make_procedure function which return the procedure
    corresponding to the opened input tab
"""

import os
import platform
import subprocess
import logging
import pyqtgraph as pg

from PyQt5.QtWidgets import QStatusBar, QLineEdit
from pymeasure.display.browser import BrowserItem
from pymeasure.display.manager import Manager, Experiment
from pymeasure.display.Qt import QtCore, QtWidgets, QtGui
from pymeasure.display.widgets import (
    PlotWidget,
    BrowserWidget,
    InputsWidget,
    LogWidget,
)
from qtpy.QtWidgets import QLineEdit as DirectoryLineEdit
from pymeasure.experiment import Results

from src.classes import log, StatusBarHandler, stage, dac, hall_sensor, set_active_stage


def _apply_form_policy(form):
    """Apply inline label-beside-field policy to one QFormLayout."""
    form.setRowWrapPolicy(QtWidgets.QFormLayout.RowWrapPolicy.DontWrapRows)
    form.setLabelAlignment(
        QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
    )
    form.setFieldGrowthPolicy(
        QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
    )
    form.setVerticalSpacing(3)
    form.setHorizontalSpacing(8)
    form.setContentsMargins(4, 2, 4, 2)


def _compact_inputs_layout(widget):
    """Force every QFormLayout inside *widget* to show label and field on the
    same line (DontWrapRows).  Works whether pymeasure attaches the form
    directly to *widget* or buries it inside nested child widgets."""
    # 1. Try the widget's own top-level layout
    direct = widget.layout()
    if isinstance(direct, QtWidgets.QFormLayout):
        _apply_form_policy(direct)

    # 2. Walk all QFormLayouts reachable via findChildren (catches layouts
    #    owned by child QObjects even when not directly on a child widget)
    for form in widget.findChildren(QtWidgets.QFormLayout):
        _apply_form_policy(form)

    # 3. Also visit every child widget's own layout — this catches form layouts
    #    that Qt may not expose through findChildren in all versions/platforms
    for child in widget.findChildren(QtWidgets.QWidget):
        child_layout = child.layout()
        if isinstance(child_layout, QtWidgets.QFormLayout):
            _apply_form_policy(child_layout)


class UIWindowBase(QtWidgets.QMainWindow):
    def __init__(self,
                 procedure_class,
                 widget_list=(),
                 inputs=(),
                 displays=(),
                 parent=None,
                 directory_input=False,
                 hide_groups=True,
                 motors_widget=None,
                 ):

        super().__init__(parent)
        app = QtCore.QCoreApplication.instance()
        app.aboutToQuit.connect(self.quit)
        self.procedure_class = procedure_class
        self.inputs = inputs
        self.hide_groups = hide_groups
        self.displays = displays
        self.directory_input = directory_input
        self.log_level = logging.INFO
        self.widget_list = widget_list
        self.motors_widget = motors_widget
        log.setLevel(logging.INFO)

        self._setup_ui()
        self._layout()

    def _setup_ui(self):
        if self.directory_input:
            self.directory_label = QtWidgets.QLabel(self)
            self.directory_label.setText('Directory')
            self.directory_line = DirectoryLineEdit(parent=self)

        self.sample_name_label = QtWidgets.QLabel(self)
        self.sample_name_label.setText("Sample name:")
        self.sample_name_line = QLineEdit(self)
        self.sample_name_line.setText("MySample")

        # ── Setup toggle (Longitudinal / Polar) ───────────────────
        self._setup_mode = "longitudinal"   # internal state

        toggle_container = QtWidgets.QWidget(self)
        toggle_container.setObjectName("setupToggle")
        toggle_layout = QtWidgets.QHBoxLayout(toggle_container)
        toggle_layout.setContentsMargins(3, 3, 3, 3)
        toggle_layout.setSpacing(2)

        setup_lbl = QtWidgets.QLabel("Setup:", toggle_container)
        setup_lbl.setObjectName("liveLabel")
        toggle_layout.addWidget(setup_lbl)

        self._btn_longitudinal = QtWidgets.QPushButton("Longitudinal", toggle_container)
        self._btn_polar        = QtWidgets.QPushButton("Polar",        toggle_container)
        self._btn_longitudinal.setObjectName("setupBtnActive")
        self._btn_polar.setObjectName("setupBtnInactive")
        self._btn_longitudinal.clicked.connect(lambda: self._set_setup_mode("longitudinal"))
        self._btn_polar.clicked.connect(lambda: self._set_setup_mode("polar"))
        toggle_layout.addWidget(self._btn_longitudinal)
        toggle_layout.addWidget(self._btn_polar)
        toggle_layout.addStretch()
        self.setup_toggle_widget = toggle_container

        self.repetitions_label = QtWidgets.QLabel(self)
        self.repetitions_label.setText("Number of experiment to perform:")
        self.repetitions_line = QLineEdit(self)
        self.repetitions_line.setText("1")

        self.queue_button = QtWidgets.QPushButton('Queue', self)
        self.queue_button.clicked.connect(self._queue)

        self.abort_button = QtWidgets.QPushButton('Abort', self)
        self.abort_button.setEnabled(False)
        self.abort_button.clicked.connect(self.abort)

        self.browser_widget = BrowserWidget(
            self.procedure_class[0],
            self.displays,
            [],
            parent=self
        )
        self.browser_widget.show_button.clicked.connect(self.show_experiments)
        self.browser_widget.hide_button.clicked.connect(self.hide_experiments)
        self.browser_widget.clear_button.clicked.connect(self.clear_experiments)
        self.browser_widget.open_button.clicked.connect(self.open_experiment)
        self.browser = self.browser_widget.browser

        self.browser.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.browser.customContextMenuRequested.connect(self.browser_item_menu)
        self.browser.itemChanged.connect(self.browser_item_changed)

        self.inputs = [InputsWidget(
            self.procedure_class[i],
            self.inputs[i],
            parent=self,
            hide_groups=self.hide_groups,
        ) for i in range(len(self.procedure_class))]

        # Force label | field side-by-side layout in every procedure panel
        for iw in self.inputs:
            _compact_inputs_layout(iw)

        self.manager = Manager(self.widget_list,
                               self.browser,
                               log_level=self.log_level,
                               parent=self)
        self.manager.abort_returned.connect(self.abort_returned)
        self.manager.queued.connect(self.queued)
        self.manager.running.connect(self.running)
        self.manager.finished.connect(self.finished)
        self.manager.log.connect(log.handle)

    def _set_setup_mode(self, mode: str):
        """Switch between 'longitudinal' and 'polar' setup modes.
        Updates button styling and redirects the save directory to the
        appropriate subfolder (<base>/<date>/longitudinal|polar/).
        """
        self._setup_mode = mode
        set_active_stage(mode)  # redirect stage calls in all procedures
        self._btn_longitudinal.setObjectName(
            "setupBtnActive" if mode == "longitudinal" else "setupBtnInactive")
        self._btn_polar.setObjectName(
            "setupBtnActive" if mode == "polar" else "setupBtnInactive")
        # Force QSS re-evaluation after objectName change
        self._btn_longitudinal.style().unpolish(self._btn_longitudinal)
        self._btn_longitudinal.style().polish(self._btn_longitudinal)
        self._btn_polar.style().unpolish(self._btn_polar)
        self._btn_polar.style().polish(self._btn_polar)

    @property
    def setup_mode(self) -> str:
        return self._setup_mode

    def showEvent(self, event):
        """Re-apply compact inputs layout after the window is first shown.
        This is necessary because some Qt/pymeasure versions reset the form
        layout policy during the first paint pass."""
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._reapply_compact_inputs)

    def _reapply_compact_inputs(self):
        for iw in self.inputs:
            _compact_inputs_layout(iw)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _layout(self):
        self.main = QtWidgets.QWidget(self)

        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)

        self.handler = StatusBarHandler(self.statusBar)
        self.handler.setLevel(logging.INFO)
        log.addHandler(self.handler)

        # ── Procedure selector (PINNED – always visible, wraps to 2 rows) ────
        #
        # Uses a grid of checkable QPushButtons + QStackedWidget instead of
        # QTabWidget so all procedure names stay visible even when the panel
        # is narrow.  Buttons are laid out 3-per-row; a second row appears
        # automatically whenever there are more than 3 procedures.

        self._proc_btn_group = QtWidgets.QButtonGroup(self.main)
        self._proc_btn_group.setExclusive(True)

        btn_bar = QtWidgets.QWidget()
        btn_bar.setObjectName("procBtnBar")
        btn_bar_layout = QtWidgets.QGridLayout(btn_bar)
        btn_bar_layout.setContentsMargins(4, 4, 4, 4)
        btn_bar_layout.setSpacing(3)

        _BTN_COLS = 2           # max buttons per row — change to taste
        for i, proc_cls in enumerate(self.procedure_class):
            btn = QtWidgets.QPushButton(proc_cls.name)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setObjectName("procTabBtnActive" if i == 0 else "procTabBtnInactive")
            btn_bar_layout.addWidget(btn, i // _BTN_COLS, i % _BTN_COLS)
            self._proc_btn_group.addButton(btn, i)

        # Switch visible panel when a button is clicked; also update styling
        self._proc_stack = QtWidgets.QStackedWidget()

        def _on_proc_selected(btn_id):
            self._proc_stack.setCurrentIndex(btn_id)
            for bid in range(len(self.procedure_class)):
                b = self._proc_btn_group.button(bid)
                b.setObjectName("procTabBtnActive" if bid == btn_id else "procTabBtnInactive")
                b.style().unpolish(b)
                b.style().polish(b)

        self._proc_btn_group.idClicked.connect(_on_proc_selected)

        # One scroll area per procedure so the button bar never scrolls away
        for i in range(len(self.procedure_class)):
            self.inputs[i].setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Minimum,
                QtWidgets.QSizePolicy.Policy.Fixed,
            )

            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            scroll.setWidget(self.inputs[i])

            self._proc_stack.addWidget(scroll)

        # Combine button bar + stacked content into one widget
        proc_selector = QtWidgets.QWidget()
        proc_selector.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        proc_sel_layout = QtWidgets.QVBoxLayout(proc_selector)
        proc_sel_layout.setContentsMargins(0, 0, 0, 0)
        proc_sel_layout.setSpacing(0)
        proc_sel_layout.addWidget(btn_bar, stretch=0)   # pinned at top
        proc_sel_layout.addWidget(self._proc_stack, stretch=1)

        # Keep a reference so get_selected_tab_index() works
        self.tabs_exp = None

        inputs_widget = proc_selector      # alias kept for left_widget below
        inputs_widget.setMinimumWidth(300)

        # ── Fixed footer: sample name, setup toggle, repetitions, directory, queue ──
        footer_widget = QtWidgets.QWidget()
        footer_widget.setObjectName("inputsFooter")
        footer_vbox = QtWidgets.QVBoxLayout(footer_widget)
        footer_vbox.setContentsMargins(8, 8, 8, 8)
        footer_vbox.setSpacing(4)

        footer_vbox.addWidget(self.sample_name_label)
        footer_vbox.addWidget(self.sample_name_line)
        footer_vbox.addWidget(self.setup_toggle_widget)
        footer_vbox.addWidget(self.repetitions_label)
        footer_vbox.addWidget(self.repetitions_line)
        # directory_label / directory_line only exist when directory_input=True
        if self.directory_input:
            footer_vbox.addWidget(self.directory_label)
            footer_vbox.addWidget(self.directory_line)

        hbox = QtWidgets.QHBoxLayout()
        hbox.addWidget(self.queue_button)
        hbox.addWidget(self.abort_button)
        footer_vbox.addLayout(hbox)

        # ── Left column: pinned tab bar on top, fixed footer below ───────
        left_widget = QtWidgets.QWidget()
        left_vbox = QtWidgets.QVBoxLayout(left_widget)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        left_vbox.setSpacing(0)
        left_vbox.addWidget(inputs_widget, stretch=1)   # tabs_exp fills the space
        left_vbox.addWidget(footer_widget, stretch=0)



        # Right column layout:
        #
        #  ┌──────────────────────┬───────────────┐
        #  │  data tabs           │ Motor control │  ← splitter_top (horizontal)
        #  ├──────────────────────┴───────────────┤
        #  │  experiment browser                  │  ← browser_widget
        #  └──────────────────────────────────────┘
        #   all wrapped in splitter_right (vertical)

        self.tabs = QtWidgets.QTabWidget(self.main)
        for wdg in self.widget_list:
            self.tabs.addTab(wdg, wdg.name)

        splitter_right = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)

        if self.motors_widget is not None:
            self.motors_tab_widget = QtWidgets.QTabWidget(self.main)

            # Accept either a single widget or a tuple/list of widgets
            motor_widgets = self.motors_widget if isinstance(self.motors_widget, (list, tuple)) else (self.motors_widget,)
            for mw in motor_widgets:
                self.motors_tab_widget.addTab(mw, mw.name)

            # Horizontal splitter: data tabs left, motor control right
            splitter_top = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
            splitter_top.addWidget(self.tabs)
            splitter_top.addWidget(self.motors_tab_widget)
            splitter_top.setStretchFactor(0, 3)   # data tabs get more width
            splitter_top.setStretchFactor(1, 1)   # motor control compact

            splitter_right.addWidget(splitter_top)
            splitter_right.addWidget(self.browser_widget)
            splitter_right.setStretchFactor(0, 3)   # top area
            splitter_right.setStretchFactor(1, 2)   # browser gets more room
            splitter_right.setSizes([520, 280])      # pin initial pixel heights
        else:
            splitter_right.addWidget(self.tabs)
            splitter_right.addWidget(self.browser_widget)

        left_widget.setMinimumWidth(380)
        left_widget.setMaximumWidth(560)

        # Prevent the right panel from ever squeezing into the left panel.
        # splitter respects child minimumWidth, so this keeps both panels
        # fully visible at any window size.
        splitter_right.setMinimumWidth(480)

        splitter_main = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter_main.addWidget(left_widget)
        splitter_main.addWidget(splitter_right)
        splitter_main.setStretchFactor(0, 0)   # left: fixed, don't stretch
        splitter_main.setStretchFactor(1, 1)   # right: takes all extra space

        main_layout = QtWidgets.QHBoxLayout(self.main)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(splitter_main)

        self.main.setLayout(main_layout)
        self.setCentralWidget(self.main)

        # Hard minimum: left (380) + right (480) + handle margin
        self.setMinimumSize(870, 600)
        self.resize(1200, 900)
        self.main.show()

    def get_selected_tab_index(self):
        idx = self._proc_btn_group.checkedId()
        return idx if idx >= 0 else 0

    def quit(self, evt=None):
        if self.manager.is_running():
            self.abort()

        self.close()

    def browser_item_changed(self, item, column):
        if column == 0:
            state = item.checkState(0)
            experiment = self.manager.experiments.with_browser_item(item)
            if state == QtCore.Qt.CheckState.Unchecked:
                for wdg, curve in zip(self.widget_list, experiment.curve_list):
                    wdg.remove(curve)
            else:
                for wdg, curve in zip(self.widget_list, experiment.curve_list):
                    wdg.load(curve)

    def browser_item_menu(self, position):
        item = self.browser.itemAt(position)

        if item is not None:
            experiment = self.manager.experiments.with_browser_item(item)

            menu = QtWidgets.QMenu(self)

            # Open
            action_open = QtGui.QAction(menu)
            action_open.setText("Open Data Externally")
            action_open.triggered.connect(
                lambda: self.open_file_externally(experiment.results.data_filename))
            menu.addAction(action_open)

            # Change Color
            action_change_color = QtGui.QAction(menu)
            action_change_color.setText("Change Color")
            action_change_color.triggered.connect(
                lambda: self.change_color(experiment))
            menu.addAction(action_change_color)

            # Remove
            action_remove = QtGui.QAction(menu)
            action_remove.setText("Remove Graph")
            if self.manager.is_running():
                if self.manager.running_experiment() == experiment:  # Experiment running
                    action_remove.setEnabled(False)
            action_remove.triggered.connect(lambda: self.remove_experiment(experiment))
            menu.addAction(action_remove)

            # Delete
            action_delete = QtGui.QAction(menu)
            action_delete.setText("Delete Data File")
            if self.manager.is_running():
                if self.manager.running_experiment() == experiment:  # Experiment running
                    action_delete.setEnabled(False)
            action_delete.triggered.connect(lambda: self.delete_experiment_data(experiment))
            menu.addAction(action_delete)

            # Use parameters
            action_use = QtGui.QAction(menu)
            action_use.setText("Use These Parameters")
            action_use.triggered.connect(
                lambda: self.set_parameters(experiment.procedure.parameter_objects()))
            menu.addAction(action_use)
            menu.exec(self.browser.viewport().mapToGlobal(position))

    def remove_experiment(self, experiment):
        reply = QtWidgets.QMessageBox.question(self, 'Remove Graph',
                                               "Are you sure you want to remove the graph?",
                                               QtWidgets.QMessageBox.StandardButton.Yes |
                                               QtWidgets.QMessageBox.StandardButton.No,
                                               QtWidgets.QMessageBox.StandardButton.No)
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self.manager.remove(experiment)

    def delete_experiment_data(self, experiment):
        reply = QtWidgets.QMessageBox.question(self, 'Delete Data',
                                               "Are you sure you want to delete this data file?",
                                               QtWidgets.QMessageBox.StandardButton.Yes |
                                               QtWidgets.QMessageBox.StandardButton.No,
                                               QtWidgets.QMessageBox.StandardButton.No)
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self.manager.remove(experiment)
            os.unlink(experiment.data_filename)

    def show_experiments(self):
        root = self.browser.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setCheckState(0, QtCore.Qt.CheckState.Checked)

    def hide_experiments(self):
        root = self.browser.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)

    def clear_experiments(self):
        self.manager.clear()

    def _detect_procedure_class(self, filename):
        """
        Peek at the ``#Procedure:`` line in the CSV header and return the
        matching procedure class from ``self.procedure_class``.

        Handles both old and new module paths by comparing only the class
        name (e.g. ``B_Sweep``), so files written before a refactor still
        open correctly.  Falls back to the first registered procedure if no
        match is found.
        """
        class_map = {cls.__name__: cls for cls in self.procedure_class}
        try:
            with open(filename, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.startswith("#"):
                        break
                    if line.startswith("#Procedure:"):
                        # e.g. "<src.procedures.b_sweep_proc.B_Sweep>"
                        proc_str = line.split(":", 1)[-1].strip().strip("<>")
                        class_name = proc_str.split(".")[-1]   # "B_Sweep"
                        matched = class_map.get(class_name)
                        if matched is not None:
                            log.info(
                                f"Detected procedure '{class_name}' from file header."
                            )
                            return matched
                        log.warning(
                            f"Procedure '{class_name}' not found in registered classes "
                            f"{list(class_map.keys())}; falling back to "
                            f"'{self.procedure_class[0].__name__}'."
                        )
        except Exception as exc:
            log.warning(f"Could not read procedure class from '{filename}': {exc}")
        return self.procedure_class[0]

    def open_experiment(self):
        filenames, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self,
            "Open Experiment Data",
            self.directory if self.directory_input else "",
            "CSV Files (*.csv);;All Files (*)",
        )
        for filename in filenames:
            if not filename:
                continue
            if filename in self.manager.experiments:
                QtWidgets.QMessageBox.warning(
                    self, "Load Error",
                    "The file %s cannot be opened twice." % os.path.basename(filename)
                )
            else:
                procedure_class = self._detect_procedure_class(filename)
                results = Results.load(filename, procedure_class=procedure_class)
                # ── Backward-compatibility column renames ──────────────────
                # Old files used different units in column headers.
                # Rename them in-place so the plot axes resolve correctly.
                _COLUMN_ALIASES = {
                    "Magnetic Field (mT)": "Magnetic Field (T)",
                    "X Position (mm)":     "X Position (m)",
                    "Y Position (mm)":     "Y Position (m)",
                }
                existing = set(results.data.columns)
                rename_map = {
                    old: new
                    for old, new in _COLUMN_ALIASES.items()
                    if old in existing and new not in existing
                }
                if rename_map:
                    results.data.rename(columns=rename_map, inplace=True)
                    if "Magnetic Field (mT)" in rename_map:
                        results.data["Magnetic Field (T)"] /= 1000.0
                    if "X Position (mm)" in rename_map:
                        results.data["X Position (m)"] /= 1000.0
                    if "Y Position (mm)" in rename_map:
                        results.data["Y Position (m)"] /= 1000.0
                    log.info(
                        f"Renamed legacy columns for '{os.path.basename(filename)}': "
                        + ", ".join(f"{o} -> {n}" for o, n in rename_map.items())
                    )
                experiment = self.new_experiment(results)
                for curve in experiment.curve_list:
                    if curve:
                        curve.update_data()
                experiment.browser_item.progressbar.setValue(100)
                self.manager.load(experiment)
                log.info('Opened data file %s' % filename)

    def change_color(self, experiment):
        color = QtWidgets.QColorDialog.getColor(
            parent=self)
        if color.isValid():
            pixelmap = QtGui.QPixmap(24, 24)
            pixelmap.fill(color)
            experiment.browser_item.setIcon(0, QtGui.QIcon(pixelmap))
            for wdg, curve in zip(self.widget_list, experiment.curve_list):
                wdg.set_color(curve, color=color)

    def open_file_externally(self, filename):
        """ Method to open the datafile using an external editor or viewer. Uses the default
        application to open a datafile of this filetype, but can be overridden by the child
        class in order to open the file in another application of choice.
        """
        system = platform.system()
        if (system == 'Windows'):
            # The empty argument after the start is needed to be able to cope
            # correctly with filenames with spaces
            _ = subprocess.Popen(['start', '', filename], shell=True)
        elif (system == 'Linux'):
            _ = subprocess.Popen(['xdg-open', filename])
        elif (system == 'Darwin'):
            _ = subprocess.Popen(['open', filename])
        else:
            raise Exception("{cls} method open_file_externally does not support {system} OS".format(
                cls=type(self).__name__, system=system))

    def make_procedure(self):
        if not isinstance(self.inputs[self.get_selected_tab_index()], InputsWidget):
            raise Exception("ManagedWindow can not make a Procedure"
                            " without a InputsWidget type")
        # Return the procedure corresponding to the open tab
        procedure = self.inputs[self.get_selected_tab_index()].get_procedure()
        procedure.set_sample_name(self.sample_name_line.text())
        return procedure

    def new_curve(self, wdg, results, color=None, **kwargs):
        if color is None:
            color = pg.intColor(self.browser.topLevelItemCount() % 8)
        return wdg.new_curve(results, color=color, **kwargs)

    def new_experiment(self, results, curve=None):
        if curve is None:
            curve_list = []
            for wdg in self.widget_list:
                curve_list.append(self.new_curve(wdg, results))
        else:
            curve_list = curve[:]

        curve_color = pg.intColor(0)
        for wdg, curve in zip(self.widget_list, curve_list):
            if isinstance(wdg, PlotWidget):
                curve_color = curve.opts['pen'].color()
                break

        browser_item = BrowserItem(results, curve_color)
        return Experiment(results, curve_list, browser_item)

    def set_parameters(self, parameters):
        """ This method should be overwritten by the child class. The
        parameters argument is a dictionary of Parameter objects.
        The Parameters should overwrite the GUI values so that a user
        can click "Queue" to capture the same parameters.
        """
        if not isinstance(self.inputs[0], InputsWidget):
            raise Exception("ManagedWindow can not set parameters"
                            " without a InputsWidget")
        self.inputs[0].set_parameters(parameters)

    def _queue(self, checked):
        """ This method is a wrapper for the `self.queue` method to be connected
        to the `queue` button. It catches the positional argument that is passed
        when it is called by the button and calls the `self.queue` method without
        any arguments.
        """
        for i in range(self.number_repetitions):
            self.queue()

    def queue(self, procedure=None):
        raise NotImplementedError(
            "Abstract method ManagedWindow.queue not implemented")

    def abort(self):
        self.abort_button.setEnabled(False)
        self.abort_button.setText("Resume")
        self.abort_button.clicked.disconnect()
        self.abort_button.clicked.connect(self.resume)
        try:
            self.manager.abort()
        except:  # noqa
            log.error('Failed to abort experiment', exc_info=True)
            self.abort_button.setText("Abort")
            self.abort_button.clicked.disconnect()
            self.abort_button.clicked.connect(self.abort)

    def resume(self):
        self.abort_button.setText("Abort")
        self.abort_button.clicked.disconnect()
        self.abort_button.clicked.connect(self.abort)
        if self.manager.experiments.has_next():
            self.manager.resume()
        else:
            self.abort_button.setEnabled(False)

    def queued(self, experiment):
        self.abort_button.setEnabled(True)
        self.browser_widget.show_button.setEnabled(True)
        self.browser_widget.hide_button.setEnabled(True)
        self.browser_widget.clear_button.setEnabled(True)

    def running(self, experiment):
        self.browser_widget.clear_button.setEnabled(False)

    def abort_returned(self, experiment):
        if self.manager.experiments.has_next():
            self.abort_button.setText("Resume")
            self.abort_button.setEnabled(True)
        else:
            self.browser_widget.clear_button.setEnabled(True)

    def finished(self, experiment):
        if not self.manager.experiments.has_next():
            self.abort_button.setEnabled(False)
            self.browser_widget.clear_button.setEnabled(True)

    @property
    def directory(self):
        if not self.directory_input:
            raise ValueError("No directory input in the ManagedWindow")
        return self.directory_line.text()
    
    @property
    def number_repetitions(self) -> int:
        try:
            return int(self.repetitions_line.text())
        except:
            log.info("The number of repetitions should be an integer, currently using 1")
            return 1

    @directory.setter
    def directory(self, value):
        if not self.directory_input:
            raise ValueError("No directory input in the ManagedWindow")

        self.directory_line.setText(str(value))


class UIWindow(UIWindowBase):
    def __init__(self, procedure_class, x_axis=None, y_axis=None, linewidth=1, **kwargs):
        self.x_axis = x_axis
        self.y_axis = y_axis
        self.log_widget = LogWidget("Experiment Log")
        self.plot_widget = PlotWidget("Results Graph", procedure_class[0].DATA_COLUMNS, self.x_axis,
                                      self.y_axis, linewidth=linewidth)
        self.plot_widget.setMinimumSize(100, 200)

        if "widget_list" not in kwargs:
            kwargs["widget_list"] = ()
        kwargs["widget_list"] = kwargs["widget_list"] + (self.plot_widget, self.log_widget)

        super().__init__(procedure_class, **kwargs)
        self.directory = "C:/Users/intermag/Desktop/Data"

        # Setup measured_quantities once we know x_axis and y_axis
        self.browser_widget.browser.measured_quantities = [self.x_axis, self.y_axis]

        logging.getLogger().addHandler(self.log_widget.handler)  # needs to be in Qt context?
        log.setLevel(self.log_level)
        log.info("miniMOKE ready for action")

        # Print devices status
        if not stage.enabled:       log.info("Could not init the stage. Make sure that Kinesis is closed.")
        if not dac.enabled:         log.info("Could not init the dac. Make sure it is connected to the computer.")
        if not hall_sensor.enabled: log.info("Could not init the hallsensor. Make sure it is connected to the computer.")