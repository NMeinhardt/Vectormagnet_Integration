
# imports
import os
import sys
import traceback
from datetime import datetime
from time import sleep, time
import numpy as np
from PyQt5 import QtGui
from PyQt5.QtCore import (QObject, QRunnable, Qt, QThreadPool, pyqtSignal,
                          pyqtSlot, QTimer)
from PyQt5.QtWidgets import (QApplication, QCheckBox, QFormLayout, QFrame,
                             QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMainWindow, QPushButton, QVBoxLayout, QWidget)

from core.hardware_backend import ElectroMagnetBackend
from core.dummy_backend import DummyMagnetBackend
from core.field_current_tr import (computeCoilCurrents,
                                   computeMagneticFieldVector)
from core.backend_base import MAGNET_STATE as MagnetState



# %%
class VectorMagnetDialog(QWidget):
    """
    Window of GUI for controlling the vector magnet.

    Args:
        parent (QWidget or similar): parent window
    """

    def __init__(self, parent=None, *args):
        """Initialize widget. It is recommended to use it inside a with statement."""
        QWidget.__init__(self, parent, *args)

        # will probably be changed/removed
        self.image_path_coord_system = './gui_images/VM_Coordinate_system.png'
        self.icon_path = './gui_images/window_icon.png'

        self.setWindowTitle('Vector Magnet Control')
        self.setWindowIcon(QtGui.QIcon(self.icon_path))

        # select backend
        self.backend = DummyMagnetBackend()
        # self.backend = ElectroMagnetBackend()

        self.threads = QThreadPool()

        # initialize timers and interval
        self.currentUpdateTimer = QTimer()
        self.currentUpdateIntervals = 1000

        # set up widgets, layouts and events
        self._init_widgets()
        self._init_layout()
        self._init_events()


    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """ Ensure that connection to channels is closed. """
        self.backend.disable_field()

        # switch off QTimer for updating currents
        # self.currentUpdateTimer.stop()

        print('connection closed.')


    def _init_widgets(self):
        """ Set container's widget set. """
        # Bare labels
        self.polarCoordsLabels = [QLabel('|\U0001D435| [mT]:'),
                                    QLabel('\U0001D717 [°]:'),
                                    QLabel('\U0001D719 [°]:')] 
        self.setpointBLabels = [   QLabel('0.00 mT'),
                                    QLabel('0.000 °'),
                                    QLabel('0.000 °')]
        self.currentsLabels = [QLabel('\U0001D43C\u2081: '),
                                QLabel('\U0001D43C\u2082: '),
                                QLabel('\U0001D43C\u2083: ')]
        self.setpointCurrentLabels = [QLabel('0.000 A'),
                                   QLabel('0.000 A'),
                                   QLabel('0.000 A')]
        
        # Label for error messages
        self.labelMessages = QLabel('')
        self.labelMessages.setText("Connected to power supplies.")
        
        # Input fields for magnetic field values
        self.polarCoordsLineEdit = [ QLineEdit(parent=self),
                                    QLineEdit(parent=self),
                                    QLineEdit(parent=self)]
        for i in range(3):
            self.polarCoordsLineEdit[i].setAlignment(Qt.AlignLeft)
            self.polarCoordsLineEdit[i].setPlaceholderText('0.0')
            self.polarCoordsLineEdit[i].returnPressed.connect(self.on_set_values_button_click)

        # Buttons
        self.coordinateSystemButton = QPushButton('show reference coordinates', self)
        self.coordinateSystemButton.resize(30, 10)
        self.setFieldValuesButton = QPushButton('set field values', self)
        self.setFieldButton = QPushButton('switch on field', self)
        self.setFieldButton.setDisabled(True)

        # Label to display status (on/off) of magnet
        self.fieldStatusLabel = QLabel('off', self)
        self.fieldStatusLabel.setAlignment(Qt.AlignCenter)
        self.fieldStatusLabel.setStyleSheet("inset grey; min-height: 30px;")
        self.fieldStatusLabel.setFrameShape(QFrame.Panel)
        self.fieldStatusLabel.setFrameShadow(QFrame.Sunken)
        self.fieldStatusLabel.setLineWidth(3)

        # Checkbox for demagnetization
        self.demagnetizeCheckBox = QCheckBox('demagnetize')

        
    def _init_layout(self):
        """ Initialise container's widget layout. """
        # Set layout of upper part related to field and current values
        upperLayout = QGridLayout()
        upperLayout.addWidget(QLabel('Enter B Vector:'), 0, 1)
        upperLayout.addWidget(QLabel('B-field Setpoint:'), 0, 2)
        upperLayout.addWidget(QLabel('Applied Currents:'), 0, 4)
        for i in range(3):
            upperLayout.addWidget(self.polarCoordsLabels[i], i + 1, 0)
            upperLayout.addWidget(self.polarCoordsLineEdit[i], i + 1, 1)
            upperLayout.addWidget(self.setpointBLabels[i], i + 1, 2)
            upperLayout.addWidget(self.currentsLabels[i], i + 1, 3)
            upperLayout.addWidget(self.setpointCurrentLabels[i], i + 1, 4)
        
        # Set layout of lower part related to switching on/off field and displaying coordinate system
        fieldControlBoxLayout = QVBoxLayout()
        fieldControlBoxLayout.addWidget(self.setFieldValuesButton)
        fieldControlBoxLayout.addWidget(self.setFieldButton)
        fieldControlBoxLayout.addWidget(self.fieldStatusLabel)
        fieldControlBoxLayout.addWidget(self.demagnetizeCheckBox)
        miscBoxLayout = QVBoxLayout()
        miscBoxLayout.addWidget(self.coordinateSystemButton)
        miscBoxLayout.addWidget(self.labelMessages)
        lowerLayout = QHBoxLayout()
        lowerLayout.addLayout(fieldControlBoxLayout)
        lowerLayout.addLayout(miscBoxLayout)

        # Combine upper and lower layout
        layout = QVBoxLayout(self)
        layout.addLayout(upperLayout)
        layout.addLayout(lowerLayout)
        self.setLayout(layout)

        # Set maximum height.
        self.setMaximumHeight(self.sizeHint().height())

        # save original layout of QLineEdit widgets
        self.polarCoordsLineEditStyleSheet = self.polarCoordsLineEdit[0].styleSheet()


    def _init_events(self):
        """
        Initialise container's event handlers.
        """
        # User initiated events
        for input_field in self.polarCoordsLineEdit:
            input_field.returnPressed.connect(self.on_set_values_button_click)
        self.coordinateSystemButton.clicked.connect(self.on_coord_system_button_click)
        self.setFieldValuesButton.clicked.connect(self.on_set_values_button_click)
        self.setFieldButton.clicked.connect(self.on_switch_on_field)
        self.demagnetizeCheckBox.stateChanged.connect(self.on_demagnetization_check_button_change)

        # Backend initiated events
        self.backend.on_current_change.connect(self.on_backend_current_change)
        self.backend.on_field_status_change.connect(self.on_backend_status_change)

        # Timer initiated events
        self.currentUpdateTimer.timeout.connect(self.on_timer_current_update)

    def on_coord_system_button_click(self):
        """Open pop up window for coordinate screen"""
        self.w = CoordinatesPopUp(self.image_path_coord_system)
        self.w.show()

    def on_set_values_button_click(self):
        """Read input coordinates, check their validity and prepare to be set on the vector magnet."""

        # get input polar coordinates
        coords = [input_field.text() for input_field in self.polarCoordsLineEdit]

        # check validity, set field if valid and refuse if not valid
        mask_validity = self.valid_inputs(coords)
        if np.all(mask_validity):
            # change color of all LineEdits back to original
            for i in range(3):
                self.polarCoordsLineEdit[i].setStyleSheet(self.polarCoordsLineEditStyleSheet)

            field_coords = [float(coords[0]), float(coords[1]), float(coords[2])]
            self.backend.set_target_field(field_coords)
            self.labelMessages.setText('')
            self.setFieldButton.setEnabled(True)

            for j in range(len(field_coords)):
                unit = 'mT' if j == 0 else '°'
                self.setpointBLabels[j].setText(f'{field_coords[j]:.2f} {unit}')

        else:
            # change color of LineEdits to red
            for i in range(3):
                if mask_validity[i]: 
                    # change back to original frame for correct inputs
                    self.polarCoordsLineEdit[i].setStyleSheet(self.polarCoordsLineEditStyleSheet)
                else:
                    # color frame in red for wrong inputs
                    self.polarCoordsLineEdit[i].setStyleSheet('border: 1px solid red') 

            self.labelMessages.setText('Invalid values, check inputs!')

            if self.backend.get_magnet_status() == MagnetState.OFF:
                self.setFieldButton.setDisabled(True)

    def on_switch_on_field(self):
        """Switch on vector magnet and set field values that are currently set as class variables.
        """
        # update variables
        self.labelMessages.setText('enabling field')
        self.backend.enable_field()


    def on_switch_off_field(self):
        """ Switch off vector magnet.
        """
        self.labelMessages.setText('disabling field')
        self.backend.disable_field()

    def on_demagnetization_check_button_change(self):
        """Pass new state of checkbox to backend.

        """
        self.backend.set_demagnetization_flag(self.demagnetizeCheckBox.isChecked())

    def on_backend_current_change(self, currents: np.ndarray):
        """Update labels with new current values.

        """
        self.labelMessages.setText('read current values')
        self._update_current_labels(currents)

    def on_timer_current_update(self):
        """Measure applied currents and update label values.

        """
        self.labelMessages.setText('read current values')
        currents = self.backend.get_currents()
        self._update_current_labels(currents)

    def _update_current_labels(self, currents):
        """Update displayed currents with provided values

        """
        text = [f'{currents[0]:.3f} A',
                    f'{currents[1]:.3f} A',
                    f'{currents[2]:.3f} A']
        for i in range(len(text)):
            self.setpointCurrentLabels[i].setText(text[i])  

    def on_backend_status_change(self, status: MagnetState):
        """Update fieldStatusLabel according to new state.

        """
        print('backend status change')
        if status == MagnetState.ON:
            # update fieldStatusLabel to have green background
            height = self.fieldStatusLabel.size().height()
            self.fieldStatusLabel.setStyleSheet(f"""background-color: lime;
                                                inset grey;
                                                height: {height}px;""")
            self.fieldStatusLabel.setText('on')

            # re-define button for switching on/off magnet
            self.setFieldButton.setText('switch off field')
            try:
                self.setFieldButton.clicked.disconnect()
            except BaseException:
                pass
            self.setFieldButton.clicked.connect(self.on_switch_off_field)

            # switch on QTimer for updating currents
            self.currentUpdateTimer.start(self.currentUpdateIntervals)

        else:
            # update fieldStatusLabel to have gray background
            self.fieldStatusLabel.setStyleSheet('inset grey; min-height: 30px;')
            self.fieldStatusLabel.setText('off')

            # re-define button for switching on/off magnet
            self.setFieldButton.setText('switch on field')
            try:
                self.setFieldButton.clicked.disconnect()
            except BaseException:
                pass
            self.setFieldButton.clicked.connect(self.on_switch_on_field)
            self.setFieldButton.setEnabled(True)

            # switch off QTimer for updating currents
            self.currentUpdateTimer.stop()

        # also update currents
        currents = self.backend.get_currents()
        self.on_backend_current_change(currents)

    def updateErrorMessage(self, args):
        """
        Keep track of errors which occurred in the GUI. A different logfile may be used.

        Args:
            args (tuple): (exctype, value, traceback.format_exc()) The information about
                          the exception which will be written to the log file.
        """
        self.labelMessages.setText(f"{args[0]}: {args[1]}")

        with open('GUI_exceptions.log', 'a') as logfile:
            logfile.write(f"{datetime.now().strftime('%d-%m-%y_%H:%M:%S')}: "
                          f"{args[0]}, {args[1]}\n{args[2]}\n")

    @staticmethod
    def valid_inputs(values):
        """
        Test whether all values are valid float values and whether the angles are correct.

        Args:
            values (list): [magnitude, theta, phi] is a list of length 3 containing spherical
                           coordinates of desired field. Accepted ranges: 0 <= magnitude;
                           0 <= theta <= 180; 0 <= phi < 360

        Returns:
            nd-array of bools: True if a vlaue is valid and False otherwise, keeps the same order as in values
        """
        mask_validity = np.ones(3, dtype=bool)
        for i, v in enumerate(values):

            # test whether all values are float
            try:
                float(v) 
            except BaseException:
                mask_validity[i] = False
            else:
                # check magnitude and polar angle individually, since here values are bounded
                if i==0 and float(v) < 0:
                    mask_validity[i] = False
                if i==1 and (float(v) > 180 or float(v) < 0):
                    mask_validity[i] = False
                if i==3 and (float(v) >= 360 or float(v) < 0):
                    mask_validity[i] = False

        return mask_validity




class CoordinatesPopUp(QWidget):
    """UI Widget: Pop up window for depicting graphically the coordinate system.

    """

    def __init__(self, image_path, *args):
        """Instance constructor.

        :param image_path: path pointing to the image used for the coordinates
        """
        QWidget.__init__(self, *args)
        self.title = "Image Viewer"
        self.setWindowTitle(self.title)

        label = QLabel(self)
        pixmap = QtGui.QPixmap(image_path)
        pixmap_scaled = pixmap.scaled(750, 750, Qt.KeepAspectRatio)
        label.setPixmap(pixmap_scaled)
        self.resize(pixmap_scaled.width(), pixmap_scaled.height())






if __name__ == '__main__':

    app = QApplication(sys.argv)

    with VectorMagnetDialog() as dialog:
        dialog.show()

        sys.exit(app.exec_())
# %%
