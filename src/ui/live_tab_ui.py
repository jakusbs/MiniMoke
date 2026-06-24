from time import sleep
import numpy as np
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QGridLayout, QVBoxLayout, QLabel, QWidget, QPushButton, QApplication, QHBoxLayout
from pymeasure.display.widgets import TabWidget
from PyQt5.QtCore import QThread, pyqtSignal, Qt

from src.classes import dac
from src.classes import log
from src.classes import hall_sensor

class HallSensorThread(QThread):
    sensor_data_signal = pyqtSignal(float)

    def __init__(self):
        super().__init__()

    def run(self):
        while True:
            if not hall_sensor.reserved:
                sensor_data = hall_sensor.read_mT()
                if sensor_data: self.sensor_data_signal.emit(sensor_data)
            else:
                sleep(1)

    def zero_sensor_value(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        hall_sensor.zeroing()
        QApplication.restoreOverrideCursor()
        log.info("Zeroing Hall sensor done")

class VoltageThread(QThread):
    balanced_diodes_signal = pyqtSignal(dict)

    def __init__(self):
        super().__init__()

    def run(self):
        while True:
            if not dac.reserved:
                if not dac.status_setup:
                    dac.setup_aquisition(acquisition_time=0.5, modulation_amp=0.)
                dac.start_tasks()
                balanced_diodes_data, intensity_diode_data = dac.read_data()

                output = {
                    "bd": np.mean(balanced_diodes_data),
                    "id": np.mean(intensity_diode_data)
                }
                self.balanced_diodes_signal.emit(output)
            else:
                sleep(1)

class LiveTab(TabWidget, QWidget):
    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name

        # Create the threads FIRST so buttons can connect to them
        self.voltage_thread = VoltageThread()
        self.voltage_thread.balanced_diodes_signal.connect(self.update_voltage_value)
        self.voltage_thread.start()

        self.hall_sensor_thread = HallSensorThread()
        self.hall_sensor_thread.sensor_data_signal.connect(self.update_sensor_value)
        self.hall_sensor_thread.start()

        # Fonts
        label_font = QFont("Segoe UI", 11)
        label_font.setWeight(QFont.Normal)

        value_font = QFont("Consolas", 36)
        value_font.setWeight(QFont.Light)

        # Helper to build a measurement card (label above value)
        def make_row(label_text, placeholder):
            container = QWidget(self)
            container.setObjectName("liveRow")
            vbox = QVBoxLayout(container)
            vbox.setContentsMargins(16, 12, 16, 12)
            vbox.setSpacing(4)

            lbl = QLabel(label_text, container)
            lbl.setObjectName("liveLabel")
            lbl.setFont(label_font)

            val = QLabel(placeholder, container)
            val.setObjectName("liveValue")
            val.setFont(value_font)

            vbox.addWidget(lbl)
            vbox.addWidget(val)
            return container, val

        # Build cards
        row_id,   self.id_value          = make_row("Intensity diode voltage",  "— mV")
        row_bd,   self.bd_value          = make_row("Balanced diodes voltage",  "— mV")
        row_hall, self.hall_sensor_value = make_row("Magnetic field",           "— mT")

        # Main layout — three cards side by side
        layout = QGridLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)

        layout.addWidget(row_id,   0, 0)
        layout.addWidget(row_bd,   0, 1)
        layout.addWidget(row_hall, 0, 2)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        self.zero_button = QPushButton("Hall sensor zeroing")
        self.zero_button.clicked.connect(self.hall_sensor_thread.zero_sensor_value)

        button_layout.addWidget(self.zero_button)
        button_layout.addStretch()

        layout.addLayout(button_layout, 1, 0, 1, 3)
        layout.setRowStretch(0, 1)

        self.setLayout(layout)

    def update_sensor_value(self, sensor_value):
        self.hall_sensor_value.setText(f'{sensor_value:.6f}mT')

    def update_voltage_value(self, voltage_value): 
        self.bd_value.setText(f'{(voltage_value["bd"]*1000.):.6f} mV')
        self.id_value.setText(f'{(voltage_value["id"]*1000.):.6f} mV')