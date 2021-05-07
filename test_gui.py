
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
from core.backend_base import MAGNET_STATE as MagnetState
from core.backend_base import CURRENT_TASK as CurrentTask
from core.backend_base import CurrentLimitExceeded



# %%
class SynchroniserSignals(QObject):
    """Anciallary class with the only purpose of providing and emitting pyqtSignals, 
    thereby enabling synchronisation among various instances of VectorMagnetDialogs. 

    """
    on_input_fields_edited = pyqtSignal(np.ndarray)
    on_correct_inputs = pyqtSignal()
    on_invalid_inputs = pyqtSignal(np.ndarray, str)

    def emit_on_correct_inputs(self):
        self.on_correct_inputs.emit()

    def emit_on_invalid_inputs(self, values : np.ndarray, message : str):
        self.on_invalid_inputs.emit(values, message)

    def emit_on_input_fields_edited(self, values : np.ndarray):
        self.on_input_fields_edited.emit(values)


class VectorMagnetDialog(QWidget):
    """UI Widget: Vector Magnet controller.

    """
    # store and update inputs of QLineEdit fields as class variables for synchronization of multiple instances 
    max_length_input_fields = 10
    typed_inputs = np.array(['', '', ''], dtype = np.dtype(f'U{max_length_input_fields}'))

    def __init__(self, backend, parent = None, synchroniser : SynchroniserSignals = SynchroniserSignals(), *args):
        """Instance constructor.

        :param parent: Associated parent widget.
        :param synchroniser: ancillary class whose only purpose is to emit signals that can be observed 
            by all widget instances. By passing it as an keyword argument, all related signals are bound 
            to the synchroniser and all widget instances are able to observe it. If the signals were defined
            as class attributes, they would be bound to the particular instance and other instances could 
            not be connected to them. 
        
        """
        QWidget.__init__(self, parent, *args)

        self.backend = backend
        self.synchroniser = synchroniser

        # initialize timers and interval
        self.currentUpdateTimer = QTimer()
        self.currentUpdateIntervals = 1000

        # set up widgets, layouts and events
        self._init_widgets()
        self._init_layout()
        self._init_events()

        # path of images
        self.image_path_coord_system = './gui_images/VM_Coordinate_system.png'
        self.icon_path = './gui_images/window_icon.png'

        self.setWindowTitle('Vector Magnet Control')
        self.setWindowIcon(QtGui.QIcon(self.icon_path))


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
        self.label_text_currents = ['\U0001D43C\u2081', '\U0001D43C\u2082', '\U0001D43C\u2083']

        # get backend's field setpoint, magnet status, applied currents and demagnetization flag, 
        # such that new widget instances start with actual values set by preexisting instances 
        initial_field_setpoint = self.backend.get_target_field(cartesian=False)
        initial_currents = self.backend.get_currents()
        magnet_status = self.backend.get_magnet_status()
        demagnetization_flag = self.backend.get_demagnetization_flag()

        # display actual setpoints and currents
        self.setpointBLabels = [   QLabel(f'{initial_field_setpoint[0]:.2f} mT'),
                                    QLabel(f'{initial_field_setpoint[1]:.2f} °'),
                                    QLabel(f'{initial_field_setpoint[2]:.2f} °')]
        self.setpointCurrentLabels = [QLabel(f'{self.label_text_currents[0]}: {initial_currents[0]: .3f} A'),
                                   QLabel(f'{self.label_text_currents[1]}: {initial_currents[0]: .3f} A'),
                                   QLabel(f'{self.label_text_currents[2]}: {initial_currents[0]: .3f} A')]
        
        # Label for error messages
        self.labelMessages = QLabel('')
        
        # Input fields for magnetic field values
        self.polarCoordsLineEdit = [ QLineEdit(parent=self),
                                    QLineEdit(parent=self),
                                    QLineEdit(parent=self)]
        for i in range(3):
            self.polarCoordsLineEdit[i].setAlignment(Qt.AlignLeft)
            if self.typed_inputs[i] == '':
                self.polarCoordsLineEdit[i].setPlaceholderText('0.0')
            else:
                self.polarCoordsLineEdit[i].setText(self.typed_inputs[i])
            self.polarCoordsLineEdit[i].setMaxLength(self.max_length_input_fields)
            self.polarCoordsLineEdit[i].setFixedWidth(80)

        # Buttons
        self.coordinateSystemButton = QPushButton('show reference coordinates', self)
        self.coordinateSystemButton.resize(30, 10)
        self.setFieldValuesButton = QPushButton('set field values', self)
        if magnet_status == MagnetState.OFF:
            self.setFieldButton = QPushButton('switch on field', self)
            self.setFieldButton.setDisabled(True)
        else:
            self.setFieldButton = QPushButton('switch off field', self)
            self.setFieldButton.setDisabled(False)

        # Label to display status (on/off) of magnet
        self.fieldStatusLabel = QLabel('', self)
        self.fieldStatusLabel.setAlignment(Qt.AlignCenter)
        self.fieldStatusLabel.setFrameShape(QFrame.Panel)
        self.fieldStatusLabel.setFrameShadow(QFrame.Sunken)
        self.fieldStatusLabel.setLineWidth(3)
        if magnet_status == MagnetState.OFF:
            self.fieldStatusLabel.setStyleSheet("inset grey; min-height: 30px;")
            self.fieldStatusLabel.setText('off')
        else:
            height = self.fieldStatusLabel.size().height()
            self.fieldStatusLabel.setStyleSheet(f"""background-color: lime;
                                                inset grey;
                                                height: {height}px;""")
            self.fieldStatusLabel.setText('on')

        # Checkbox for demagnetization
        self.demagnetizeCheckBox = QCheckBox('demagnetize')
        if demagnetization_flag:
            self.demagnetizeCheckBox.setCheckState(Qt.Checked)

        
    def _init_layout(self):
        """ Initialise container's widget layout. """
        # Set layout of upper part related to field and current values
        upperLayout = QGridLayout()
        upperLayout.addWidget(QLabel('Enter \U0001D435-Vector:'), 0, 1)
        upperLayout.addWidget(QLabel('\U0001D435-Setpoint:'), 0, 2)
        upperLayout.addWidget(QLabel('Applied Currents:'), 0, 3)
        for i in range(3):
            upperLayout.addWidget(self.polarCoordsLabels[i], i + 1, 0)
            upperLayout.addWidget(self.polarCoordsLineEdit[i], i + 1, 1)
            upperLayout.addWidget(self.setpointBLabels[i], i + 1, 2)
            upperLayout.addWidget(self.setpointCurrentLabels[i], i + 1, 3, alignment = Qt.AlignLeft)
        
        # Set layout of lower part related to switching on/off field and displaying coordinate system
        fieldControlBoxLayout = QVBoxLayout()
        fieldControlBoxLayout.addWidget(self.setFieldValuesButton)
        fieldControlBoxLayout.addWidget(self.setFieldButton)
        fieldControlBoxLayout.addWidget(self.fieldStatusLabel)
        miscBoxLayout = QVBoxLayout()
        miscBoxLayout.addWidget(self.coordinateSystemButton)
        miscBoxLayout.addWidget(self.demagnetizeCheckBox)
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
        """Initialise container's event handlers. """
        # User initiated events
        for input_field in self.polarCoordsLineEdit:
            input_field.returnPressed.connect(self.on_set_values_button_click)
            input_field.textEdited.connect(self.on_single_input_field_text_edited)
        self.coordinateSystemButton.clicked.connect(self.on_coord_system_button_click)
        self.setFieldValuesButton.clicked.connect(self.on_set_values_button_click)
        self.demagnetizeCheckBox.stateChanged.connect(self.on_demagnetization_check_button_change)
        if self.backend.get_magnet_status() == MagnetState.OFF:
            self.setFieldButton.clicked.connect(self.on_switch_on_field)
        else:
            self.setFieldButton.clicked.connect(self.on_switch_off_field)

        # synchroniser initiated events
        self.synchroniser.on_input_fields_edited.connect(self.on_overall_input_field_text_edited)
        self.synchroniser.on_correct_inputs.connect(self.on_correct_inputs)
        self.synchroniser.on_invalid_inputs.connect(self.on_invalid_inputs)

        # Backend initiated events
        self.backend.on_single_current_change.connect(self.on_backend_single_current_change)
        self.backend.on_field_status_change.connect(self.on_backend_status_change)
        self.backend.on_task_change.connect(self.on_backend_task_change)
        self.backend.on_field_setpoint_change.connect(self.on_backend_field_setpoint_change)
        self.backend.on_demagnetization_flag_change.connect(self.on_backend_demagnetization_flag_change)

        # Timer initiated events
        self.currentUpdateTimer.timeout.connect(self.on_timer_current_update)


    def on_coord_system_button_click(self):
        """Open pop up window for coordinate screen"""
        self.w = CoordinatesPopUp(self.image_path_coord_system)
        self.w.show()


    def on_set_values_button_click(self):
        """Read input coordinates, check their validity and prepare to be set on the vector magnet.
        """
        print(f"GUI :: magnet :: on_set_values_button_click")
        # get input polar coordinates
        coords = [input_field.text() for input_field in self.polarCoordsLineEdit]

        # check validity, set field if valid and refuse if not valid
        mask_validity = self.valid_inputs(coords)
        if np.all(mask_validity):
            
            # transform inputs to floats and combine in an array
            field_coords = np.array([float(coords[0]), float(coords[1]), float(coords[2])])

            # try to update setpoint to provided values, catch custom exception raised when field is infeasible
            try:
                self.backend.set_target_field(field_coords)
            except CurrentLimitExceeded:
                # emit signal to announce that the desired vector is infeasible to all widget instances 
                mask_infeasible_mag = np.array([False, True, True])
                message_infeasible_mag = 'Currents would exceed limits,\ntry smaller magnitude.'
                self.synchroniser.emit_on_invalid_inputs(mask_infeasible_mag, message_infeasible_mag)
            else:
                # emit signal to announce an successful input to all widget instances 
                self.synchroniser.emit_on_correct_inputs()
                
        else:
            # emit signal to announce invalid input to all widget instances 
            self.synchroniser.emit_on_invalid_inputs(mask_validity, 'Invalid values, check inputs!')


    def on_correct_inputs(self):
        """Update the style of the input fields, erase error messages and 
        enable the button for switching on the field. 
        """
        # change color of all LineEdits back to original
        for input_field in  self.polarCoordsLineEdit:
            input_field.setStyleSheet(self.polarCoordsLineEditStyleSheet)

        # erase previous messages and enable button for switching on the field
        self.labelMessages.setText('')
        self.setFieldButton.setEnabled(True)


    def on_invalid_inputs(self, mask_validity : np.ndarray, message : str):
        """Update the style of the input fields according to the provided mask, display the message and 
        disable the button for switching on the field, unless the field is already on. 
        """
        # update frame colors of LineEdits
        for i in range(3):
            if mask_validity[i]: 
                # change back to original frame for correct inputs
                self.polarCoordsLineEdit[i].setStyleSheet(self.polarCoordsLineEditStyleSheet)
            else:
                # color frame in red for wrong inputs
                self.polarCoordsLineEdit[i].setStyleSheet('border: 1px solid red') 

        # display the passed message
        self.labelMessages.setText(message)

        # disable button to switch on field unless it is already on
        if self.backend.get_magnet_status() == MagnetState.OFF:
            self.setFieldButton.setDisabled(True)


    def on_single_input_field_text_edited(self, *args):
        """Update class variable that contains the currently typed inputs and emit signal,
        such that other instances of widget get notified, too. 
        """
        self.typed_inputs[:] = [input_field.text() for input_field in self.polarCoordsLineEdit]
        self.synchroniser.emit_on_input_fields_edited(self.typed_inputs)


    def on_overall_input_field_text_edited(self, inputs : np.ndarray):
        """Input fields have been edited either in this widget instance or another one.
        Either way, update the text displayed in the input fields to synchronize all instances. 
        """
        for i in range(3):
            self.polarCoordsLineEdit[i].setText(inputs[i])


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
    

    def on_backend_single_current_change(self, current: float, channel: int):
        """Update a single label with new current values.

        """
        # if current is close to zero set it to exactly zero to avoid '-0.000 A' labels
        if np.isclose(current, 0, atol = 5e-4):
            current = 0
        text = f'{self.label_text_currents[channel]}: {current: .3f} A'
        self.setpointCurrentLabels[channel].setText(text)  


    def on_backend_field_setpoint_change(self, spherical_coords : np.ndarray):
        """Update labels of setpoints accoring to passed values.
        Since the signal connected to this function heralds a successful update of
        the field setpoint, use this function to erase any displayed error messages. 

        """
        # update labels dispaying the field setpoint
        for j in range(3):
            unit = 'mT' if j == 0 else '°'
            self.setpointBLabels[j].setText(f'{spherical_coords[j]:.2f} {unit}')
        
        # enable the button to switch on fields
        self.setFieldButton.setEnabled(True)

        # change color of all LineEdits back to original
        for input_field in  self.polarCoordsLineEdit:
            input_field.setStyleSheet(self.polarCoordsLineEditStyleSheet)

        # erase any previous error messages
        self.labelMessages.setText('')

    
    def on_backend_demagnetization_flag_change(self, flag : bool):
        """Update state of demagnetization checkbox according to passed flag.

        """
        if flag:
            self.demagnetizeCheckBox.setCheckState(Qt.Checked)
        else:
            self.demagnetizeCheckBox.setCheckState(Qt.Unchecked)


    def on_timer_current_update(self):
        """Measure applied currents and update label values.

        """
        currents = self.backend.get_currents()
        # if current is close to zero set it to exactly zero to avoid '-0.000 A' labels
        currents[np.isclose(currents, 0, atol = 5e-4)] = 0
        self._update_current_labels(currents)


    def _update_current_labels(self, currents):
        """Update displayed currents with provided values

        """
        text = [f'{self.label_text_currents[0]}: {currents[0]: .3f} A',
                    f'{self.label_text_currents[1]}: {currents[1]: .3f} A',
                    f'{self.label_text_currents[2]}: {currents[2]: .3f} A']
        for i in range(len(text)):
            self.setpointCurrentLabels[i].setText(text[i])  


    def on_backend_task_change(self, task: CurrentTask):
        """Update Message  according to new task.

        """
        if task == CurrentTask.IDLE:
            self.labelMessages.setText('')
        elif task == CurrentTask.ENABLING:
            self.labelMessages.setText('Enabling field.')
        elif task == CurrentTask.DISABLING:
            self.labelMessages.setText('Disabling field.')
        elif task == CurrentTask.SWITCHING:
            self.labelMessages.setText('Ramping field to new value.')
        elif task == CurrentTask.DEMAGNETIZING:
            self.labelMessages.setText('Demagnetizing.')


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

            # switch off QTimer for updating currents and update currents for the last time
            self.currentUpdateTimer.stop()
            self.on_timer_current_update()


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
        pixmap_scaled = pixmap.scaled(750, 750, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(pixmap_scaled)
        self.resize(pixmap_scaled.width(), pixmap_scaled.height())


if __name__ == '__main__':

    app = QApplication(sys.argv)

    # select desired backend 
    backend = DummyMagnetBackend()
    # backend = ElectroMagnetBackend()

    with VectorMagnetDialog(backend) as dialog:
        dialog.show()

        sys.exit(app.exec_())
# %%
