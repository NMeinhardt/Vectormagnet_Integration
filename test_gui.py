
# imports
import os
import sys
import threading
import traceback
from datetime import datetime
from time import sleep, time

import matplotlib as mpl
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from PyQt5 import QtGui
from PyQt5.QtCore import (QObject, QRunnable, Qt, QThreadPool, pyqtSignal,
                          pyqtSlot)
from PyQt5.QtWidgets import (QApplication, QCheckBox, QFormLayout, QFrame,
                             QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMainWindow, QPushButton, QVBoxLayout, QWidget)

from core.current_control import PowerSupplyCommands
from core.field_current_tr import (computeCoilCurrents,
                                   computeMagneticFieldVector)


# %%
class WorkerSignals(QObject):
    '''
    Defines the signals available from a running worker thread.

    Supported signals are:

    finished
        No data

    error
        tuple (exctype, value, traceback.format_exc() )

    result
        object data returned from processing, anything

    progress
        int indicating % progress

    '''
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)


class Worker(QRunnable):
    '''
    Worker thread

    Inherits from QRunnable to handle worker thread setup, signals and wrap-up.

    :param callback: The function callback to run on this worker thread. Supplied args and
                     kwargs will be passed through to the runner.
    :type callback: function
    :param args: Arguments to pass to the callback function
    :param kwargs: Keywords to pass to the callback function
    '''

    def __init__(self, fn, *args, **kwargs):
        super(Worker, self).__init__()

        # Store constructor arguments (re-used for processing)
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        '''Initialise the runner function with passed args, kwargs.'''

        # Retrieve args/kwargs here; and fire processing using them
        try:
            result = self.fn(*self.args, **self.kwargs)
        except BaseException:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            if result is not None:
                self.signals.result.emit(result)  # Return the result of the processing
        finally:
            self.signals.finished.emit()  # Done


class CoordinatesPopUp(QWidget):
    """
    Class which represents the popup window for depicting graphically the coordinate system.

    Args:
        image_path (str): path pointing to the image used for the coordinates
    """

    def __init__(self, image_path, *args):
        QWidget.__init__(self, *args)
        self.title = "Image Viewer"
        self.setWindowTitle(self.title)

        self.gui_image_folder = r'C:\Users\Magnebotix\Desktop\Qzabre_Vector_Magnet\1_Version_2_Vector_Magnet\2_Current_Source_Contol\Sensor_Current_Source_Comm\gui_images'
        self.icon_file = 'window_icon.png'

        self.setWindowIcon(QtGui.QIcon(os.path.join(self.gui_image_folder, self.icon_file)))

        label = QLabel(self)
        pixmap = QtGui.QPixmap(image_path)
        pixmap_scaled = pixmap.scaled(750, 750, Qt.KeepAspectRatio)
        label.setPixmap(pixmap_scaled)
        self.resize(pixmap_scaled.width(), pixmap_scaled.height())

# TODO: go through all TODOs in VectorMagnetDialog class once connected to IT6432 power supplies


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
        self.gui_image_folder = r'gui_images'
        self.icon_file = 'window_icon.png'

        self.setWindowTitle('Vector Magnet Control')
        self.setWindowIcon(QtGui.QIcon(os.path.join(self.gui_image_folder, self.icon_file)))

        # set class variables
        self.magnet_is_on = False

        # connect to power supplies
        # TODO: uncomment next line
        # self.commander = PowerSupplyCommands()

        # logger
        # print('open connection to power supplies')
        self.threads = QThreadPool()
        # set up required widgets
        self._create_widgets()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """ Ensure that connection to channels is closed. """
        # self.commander.closeConnection()
        print('connection closed.')

    def _create_widgets(self):
        """ Create all widgets needed for the graphical interface. """
        # set layout of window
        generalLayout = QVBoxLayout(self)

        # add input fields to enter spherical coordinates
        upperLayout = QGridLayout()

        # entriesLayout = QFormLayout()
        labels_polar_coords = [
            QLabel('|\U0001D435| [mT]:'),
            QLabel('\U0001D717 [°]:'),
            QLabel('\U0001D719 [°]:')]  # magnitude, theta, phi
        self.input_polar_coords = [
            QLineEdit(parent=self),
            QLineEdit(parent=self),
            QLineEdit(parent=self)]
        # add a label to display set magnetic field values
        self.setpoints_BField = [QLabel('0.00 mT'),
                                 QLabel('0.000 °'),
                                 QLabel('0.000 °')]

        labels_currents = [QLabel('\U0001D43C\u2081: '),
                           QLabel('\U0001D43C\u2082: '),
                           QLabel('\U0001D43C\u2083: ')]
        self.setpoints_currents = [QLabel('0.000A'),
                                   QLabel('0.000A'),
                                   QLabel('0.000A')]

        upperLayout.addWidget(QLabel('enter B Vector:'), 0, 1)
        upperLayout.addWidget(QLabel('B field Setpoint:'), 0, 2)
        upperLayout.addWidget(QLabel('Current Setpoint:'), 0, 4)

        for i in range(3):
            self.input_polar_coords[i].setAlignment(Qt.AlignLeft)
            self.input_polar_coords[i].setPlaceholderText('0.0')
            self.input_polar_coords[i].returnPressed.connect(self._onSetValues)

            upperLayout.addWidget(labels_polar_coords[i], i + 1, 0)
            upperLayout.addWidget(self.input_polar_coords[i], i + 1, 1)
            upperLayout.addWidget(self.setpoints_BField[i], i + 1, 2)
            upperLayout.addWidget(labels_currents[i], i + 1, 3)
            upperLayout.addWidget(self.setpoints_currents[i], i + 1, 4)

        generalLayout.addLayout(upperLayout)
        # layout for lower half of GUI
        lowerLayout = QHBoxLayout()

        misc = QVBoxLayout()
        self.coordinate_system_btn = QPushButton('show reference coordinates', self)
        self.coordinate_system_btn.clicked.connect(self.openCoordPopup)
        self.coordinate_system_btn.resize(30, 10)
        misc.addWidget(self.coordinate_system_btn)

        # add label for error messages related to setting field values
        self.msg_values = QLabel('')
        misc.addWidget(self.msg_values)

        # TODO: uncomment lines 219-220, 223-226, indent line 222
        # try:
        #     self.commander.openConnection()
        self.msg_values.setText("Connected to power supplies.")
        # except BaseException:
        #     traceback.print_exc()
        #     exctype, value = sys.exc_info()[:2]
        #     self.updateErrorMessage((exctype, value, traceback.format_exc()))

        fieldCtrl = QVBoxLayout()
        # add button for setting field values
        self.btn_set_values = QPushButton('set field values', self)
        self.btn_set_values.clicked.connect(self._onSetValues)
        fieldCtrl.addWidget(self.btn_set_values)

        # add button for switching on/off field, disable at first
        self.btn_set_field = QPushButton('switch on field', self)
        self.btn_set_field.clicked.connect(self._SwitchOnField)
        self.btn_set_field.setDisabled(True)
        fieldCtrl.addWidget(self.btn_set_field)

        # add a display that shows whether magnet is on or off, should be
        # a circle later
        self.lab_field_status = QLabel('off', self)
        self.lab_field_status.setAlignment(Qt.AlignCenter)
        self.lab_field_status.setStyleSheet("inset grey; min-height: 30px;")
        self.lab_field_status.setFrameShape(QFrame.Panel)
        self.lab_field_status.setFrameShadow(QFrame.Sunken)
        self.lab_field_status.setLineWidth(3)

        fieldCtrl.addWidget(self.lab_field_status)

        # add checkbox to enable/disable demagnetization
        self.check_demag = QCheckBox('demagnetize')
        fieldCtrl.addWidget(self.check_demag)

        lowerLayout.addLayout(fieldCtrl)
        lowerLayout.addLayout(misc)

        generalLayout.addLayout(lowerLayout)

        self.setLayout(generalLayout)

    def openCoordPopup(self):
        """open pop up window for coordinate screen"""

        path = os.path.join(self.gui_image_folder, 'VM_Coordinate_system.png')
        self.w = CoordinatesPopUp(path)
        self.w.show()

    def updateErrorMessage(self, args):
        """
        Keep track of errors which occurred in the GUI. A different logfile may be used.

        Args:
            args (tuple): (exctype, value, traceback.format_exc()) The information about
                          the exception which will be written to the log file.
        """
        self.msg_values.setText(f"{args[0]}: {args[1]}")

        with open('GUI_exceptions.log', 'a') as logfile:
            logfile.write(f"{datetime.now().strftime('%d-%m-%y_%H:%M:%S')}: "
                          f"{args[0]}, {args[1]}\n{args[2]}\n")

    def _onSetValues(self):
        """Read input coordinates, check their validity and prepare to be set on the vector magnet."""

        # get input polar coordinates
        coords = [input_field.text() for input_field in self.input_polar_coords]

        # check validity, set field if valid and refuse if not valid
        if self.valid_inputs(coords):
            self.field_coords = [float(coords[0]), float(coords[1]), float(coords[2])]
            self.msg_values.setText('')
            self.btn_set_field.setEnabled(True)

            for j in range(len(self.field_coords)):
                unit = 'mT' if j == 0 else '°'
                self.setpoints_BField[j].setText(f'{self.field_coords[j]:.2f} {unit}')
            # if magnet is already on, set new currents on psus immediately
            if self.magnet_is_on:
                self._SwitchOnField()

        else:
            self.msg_values.setText('Invalid values, check inputs!')

            if not self.magnet_is_on:
                self.btn_set_field.setDisabled(True)

    @staticmethod
    def valid_inputs(values):
        """
        Test whether all values are valid float values and whether the angles are correct.

        Args:
            values (list): [magnitude, theta, phi] is a list of length 3 containing spherical
                           coordinates of desired field. Accepted ranges: 0 <= magnitude;
                           0 <= theta <= 180; 0 <= phi < 360

        Returns:
            bool: True if all values are valid and False otherwise
        """
        # test whether all values are float
        try:
            [float(v) for v in values]
        except BaseException:
            return False
        else:
            # check magnitude and polar angle individually, since here values are bounded
            if float(values[0]) < 0:
                return False
            if float(values[1]) > 180 or float(values[1]) < 0:
                return False
            if float(values[2]) >= 360 or float(values[1]) < 0:
                return False

            return True

    def _SwitchOnField(self):
        """Switch on vector magnet and set field values that are currently set as class variables."""

        # update variables
        self.magnet_is_on = True

        # re-define button for switching on/off magnet
        self.lab_field_status.setStyleSheet("""background-color: lime;
                                            inset grey;
                                            min-height: 30px;""")
        self.lab_field_status.setText('on')
        self.btn_set_field.setText('switch off field')
        try:
            self.btn_set_field.clicked.disconnect()
        except BaseException:
            pass
        self.btn_set_field.clicked.connect(self._SwitchOffField)

        # actual magic
        demagnetize = self.check_demag.isChecked()
        self._setMagField(
            self.field_coords[0],
            self.field_coords[1],
            self.field_coords[2],
            demagnetize)

        # update the currents continuously
        current_updater = Worker(self.contCurrentFetch)
        current_updater.signals.error.connect(self.updateErrorMessage)

        self.threads.start(current_updater)

    def _SwitchOffField(self):
        """ Switch off vector magnet."""

        # update variables
        self.magnet_is_on = False

        # re-define button for switching on/off magnet
        self.lab_field_status.setStyleSheet('inset grey; min-height: 30px;')
        self.lab_field_status.setText('on')
        self.lab_field_status.setText('off')
        self.btn_set_field.setDisabled(True)
        self.btn_set_field.setText('switch on field')
        try:
            self.btn_set_field.clicked.disconnect()
        except BaseException:
            pass
        self.btn_set_field.clicked.connect(self._SwitchOnField)

        # actual magic
        demagnetize = self.check_demag.isChecked()
        self._disableField(demagnetize)
        self.btn_set_field.setEnabled(True)

        # update the currents to be 0 again.
        self._DisplayCurrents()

    def _DisplayCurrents(self):
        """This method is for displaying measured current values from the IT6432."""

        currents = self._getCurrents()

        if self.magnet_is_on:
            text = [f'{currents[0]:.3f}A',
                    f'{currents[1]:.3f}A',
                    f'{currents[2]:.3f}A']
        else:
            text = ['0.000A',
                    '0.000A',
                    '0.000A']
        for i in range(len(text)):
            self.setpoints_currents[i].setText(text[i])

    def contCurrentFetch(self):
        """continuously fetch current measurements from IT6432"""

        while self.magnet_is_on:
            self._DisplayCurrents()
            sleep(0.8)

    def contStatusFetch(self):
        """Fetch status bits of IT6432, display any resulting messages."""

        important_msgs = ['QER0', 'QER1', 'QER3', 'QER4', 'QER5', 'ESR3', 'OSR1']

        while self.magnet_is_on:
            message_dicts = []
            for i in range(3):
                message_dicts.append(self.commander.power_supplies[i].getStatus())

                for key in important_msgs:
                    if key in message_dicts[i].keys():
                        self.msg_values.setText('%s - on channel %d' % (message_dicts[i][key], i))

            sleep(5)

    def _setMagField(self, magnitude: float, theta: float, phi: float, demagnetize: bool):
        """
        Compute the current values required to set the desire magnetic field. Then, set them on
        each IT6432 power supply.

        Args:
            magnitude (float): B field magnitude
            theta (float): polar coordinate angle (measured from z axis)
            phi (float): azimuthal coordinate angle (measured from x axis)
            demagnetize (bool): if checked, demagnetization will be run before setting the currents
        """
        self.msg_values.setText(f'setting field ({magnitude} mT, {theta}°, {phi}°)')
        # TODO: uncomment lines 448-464
        # get magnetic field in Cartesian coordinates
        B_fieldVector = computeMagneticFieldVector(magnitude, theta, phi)
        currents = computeCoilCurrents(B_fieldVector)
        print(f'required currents: {currents} mA')

        # try:
        #     if demagnetize:
        #         self.msg_values.setText('Demagnetizing...')
        #         starting_currents = self.commander.setCurrentValues
        #         self.commander.demagnetizeCoils(starting_currents)

        #     self.commander.setCurrents(des_currents=currents)
        # except BaseException:
        #     traceback.print_exc()
        #     exctype, value = sys.exc_info()[:2]
        #     self.updateErrorMessage((exctype, value, traceback.format_exc()))

        # else:
        #     self.msg_values.setText('Currents have been set.')

    def _disableField(self, demagnetize: bool):
        """
        Set the currents to 0 and disable the IT6432.

        Args:
            demagnetize (bool): if checked, demagnetization will be run before setting the currents
        """
        self.msg_values.setText('disabling field')
        # use self.msg_magnet.setText() to output any error messages
        # TODO: uncomment lines 476-488
        # if demagnetize:
        #     self.msg_values.setText('Demagnetizing...')
        #     starting_currents = self.commander.setCurrentValues
        #     try:
        #         self.commander.demagnetizeCoils(starting_currents)
        #     except BaseException:
        #         traceback.print_exc()
        #         exctype, value = sys.exc_info()[:2]
        #         self.updateErrorMessage((exctype, value, traceback.format_exc()))

        # else:
        #     self.commander.disableCurrents()
        #     self.msg_values.setText('Power supplies ready.')

    def _getCurrents(self):
        """
        Get current measurements from each power supply.

        Returns:
            list: list of current values
        """
        self.msg_values.setText('read current values')
        # TODO: uncomment lines 499-506, change return to return currents variable
        # currents = [0, 0, 0]
        # try:
        #     for i, psu in enumerate(self.commander.power_supplies):
        #         currents[i] = psu.getMeasurement(meas_quantity='current')
        # except BaseException:
        #     traceback.print_exc()
        #     exctype, value = sys.exc_info()[:2]
        #     self.updateErrorMessage((exctype, value, traceback.format_exc()))

        return [0, 0, 0]


if __name__ == '__main__':

    app = QApplication(sys.argv)

    with VectorMagnetDialog() as dialog:
        dialog.show()

        sys.exit(app.exec_())
# %%
