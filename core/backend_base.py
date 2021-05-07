import numpy as np
import enum
import pickle
import threading
from time import sleep
from PyQt5.QtCore import QObject
from PyQt5.QtCore import pyqtSignal


@enum.unique
class CURRENT_TASK(enum.Enum):
    """Purpose of the thread.
    
    """
    ENABLING = 1
    DISABLING = 2
    DEMAGNETIZING = 3
    SWITCHING = 4
    IDLE = 5

@enum.unique
class MAGNET_STATE(enum.Enum):
    """Magnet power states.
    
    """
    ON = 1
    OFF = 2


class CurrentLimitExceeded(Exception):
    """Raised when a value that is larger than a given limit should be set.
    """
    pass

class ObserverThread(threading.Thread):
    """Thread class that checks whether ramping threads are still alive.

    """
    def __init__(self, subjects : np.ndarray, running_task : CURRENT_TASK, signal : pyqtSignal, 
                    check_demagnetization = False, *args, **kwargs):
        """
        Instance constructor.
        
        :param subjects: list or array containing all threads that are under surveillance
        :param running_task: currently running task
        :param signal: signal that is emitted when all threads in subjects have finished or demagnetization has been completed
        :param check_demagnetization: If True, also check whether all threads have passed the demagnetization stage and emit 
            a signal once this is the case. 
        """
        super().__init__(*args, **kwargs)

        # initialize variables 
        self._subjects = subjects
        self._running_task = running_task
        self._signal = signal
        self._check_demag = check_demagnetization


    def run(self):
        """Check whether threads are still alive and send a signal at the end. 
        """
        if self._check_demag:
            while(np.any([thread.is_alive() and not thread.demagnetization_completed() for thread in self._subjects])):
                sleep(0.1)
            self._signal.emit(CURRENT_TASK.DEMAGNETIZING)

        while(np.any([thread.is_alive() for thread in self._subjects])):
            sleep(0.1)

        # emit signal to herald that task has finished
        self._signal.emit(self._running_task)

class MagnetBackendBase(QObject):
    """Vector magnet backend base class.
    
    """
    # Event: current change.
    on_single_current_change = pyqtSignal(float, int)

    # Event: current change.
    on_field_status_change = pyqtSignal(MAGNET_STATE)

    # Event: change of currently status change.
    on_task_change = pyqtSignal(CURRENT_TASK)

    # Event: change of magnetic field setpoint.
    on_field_setpoint_change = pyqtSignal(np.ndarray)

    # Event: change of flag for demagnetization.
    on_demagnetization_flag_change = pyqtSignal(bool)

    # changeable parameters
    filename_model_B2I = 'model_poly3_final_B2I.sav'
    filename_model_I2B = 'model_poly3_final_I2B.sav'

    def get_currents(self) -> np.ndarray:
        """Returns currents of power supplies.

        """
        raise NotImplementedError()


    def set_currents(self, values: np.ndarray):
        """Sets the currents of power supplies.

        :param values: Current values to be set.
        """
        raise NotImplementedError()


    def enable_field(self):
        """Enables magnetic field.

        """
        raise NotImplementedError()


    def disable_field(self):
        """Disables magnetic field.

        """
        raise NotImplementedError()


    def get_magnet_status(self) -> MAGNET_STATE:
        """Returns status of magnet.

        """
        raise NotImplementedError()

    def set_demagnetization_flag(self, flag: bool):
        """Sets the demagnetization flag.

        """
        raise NotImplementedError()

    def get_demagnetization_flag(self) -> bool:
        """Returns the demagnetization flag.

        """
        raise NotImplementedError()

    def get_max_current(self) -> float:
        """Returns the maximum limit on current set by the backend.

        """
        raise NotImplementedError()
    

    def get_target_field(self, cartesian = True) -> np.ndarray:
        """Returns current setpoint of magnetic field in Cartesian (if cartesian=True, default)
        or spherical coordinates (if cartesian=False)

        """
        if cartesian:
            return self._setpoint_fields
        else:
            return self.cartesian_to_spherical(self._setpoint_fields)

    def set_target_field(self, spherical_values: np.ndarray):
        """Sets the target point of magnetic field.

        :param spherical_values: Magnetic field in spherical coordinates to be set: 
        (magnitude [mT], polar angle wrt. z axis [degrees], azimuthal angle clockwise wrt. x-axis [degrees])
        :raises CurrentLimitExceeded: If the current limit of any channel would be exceeded. 
        """
        cartesian_values = self.spherical_to_cartesian(spherical_values)
        if np.any(self._setpoint_fields != cartesian_values):  
            # estimate required currents
            required_currents = self._compute_coil_currents(cartesian_values)

            if np.any(required_currents > self.get_max_current()):
                raise CurrentLimitExceeded

            # set required currents
            self.set_currents(required_currents)
            self._setpoint_fields = cartesian_values

            # notify UI that setpoint has been changed successfully 
            self.on_field_setpoint_change.emit(spherical_values)

    @staticmethod
    def spherical_to_cartesian(spherical_coords: np.ndarray) -> np.ndarray:
        """Compute the Cartesian coordinates from spherical coordinates.

        :param spherical_coords: Magnetic field in spherical coordinates to be set: 
        (magnitude [mT], polar angle wrt. z axis [degrees], azimuthal angle clockwise wrt. x-axis [degrees])

        :returns: vector in Cartesian coordinates [Bx, By, Bz]
        :rtype: np.ndarray
        """
        # explicitly define spherical coordinates to prevent misconfusions
        magnitude, theta, phi = spherical_coords

        cartesian_vector = np.array([  np.sin(np.radians(theta)) * np.cos(np.radians(phi)),
                                        np.sin(np.radians(theta)) * np.sin(np.radians(phi)),
                                        np.cos(np.radians(theta))])

        cartesian_vector = magnitude* cartesian_vector / np.linalg.norm(cartesian_vector)
        return np.around(cartesian_vector, 3)


    @staticmethod
    def cartesian_to_spherical(cartesian_coords: np.ndarray) -> np.ndarray:
        """Compute spherical from Cartesian coordinates.

        :param cartesian_coords: Magnetic field in Cartesian coordinates to be set (x, y, z)
        :returns: vector in spherical coordinates [magnitude [mT], theta [°], phi [°]], 
        where theta is the polar angle wrt. z axis and phi the azimuthal angle clockwise wrt. x-axis.
        :rtype: np.ndarray
        """
        magnitude = np.linalg.norm(cartesian_coords)
        theta = np.degrees(np.arccos(cartesian_coords[2] / magnitude)) if magnitude > 0 else 0
        phi = np.degrees(np.arctan2(cartesian_coords[1], cartesian_coords[0])) if magnitude > 0 else 0
        return np.array([magnitude, theta, phi])


    def _compute_coil_currents(self, magnetic_field_vector: np.ndarray) -> np.ndarray:
        """Compute coil currents [mA] required to generate the desired magnetic field vector.
        Model derived from calibration measurements and saved as file.

        :param magnetic_field_vector: field vector in Cartesian coordinates and in mT
        :type magnetic_field_vector: 1d np.ndarray of length 3
        
        :returns: current vectors [A] required to generate magnetic_field_vector 
        :rtype: 1d np.ndarray of length 3
        """
        # load the model from disk
        filepath = f'./fitting_parameters/{self.filename_model_B2I}'
        [loaded_model, loaded_poly] = pickle.load(open(filepath, 'rb'))

        # preprocess test vectors, st. they have correct shape for model
        input_vector_ = loaded_poly.fit_transform(magnetic_field_vector.reshape((1, 3)))

        # estimate prediction of required currents
        current_vector = loaded_model.predict(input_vector_)
        
        return np.round(current_vector.reshape(3), 3)


    def _compute_magnetic_field(self, current_vector: np.ndarray) -> np.ndarray:
        """Compute magnetic field vector generated by the currents.

        :param current_vector: current values [A] of coils
        :type current_vector: 1d np.ndarray of length 3

        :returns: expected field vector [mT] in Cartesian coordinates generated by the applied currents 
        :rtype: 1d np.ndarray of length 3
        """
        # load the model from disk
        filepath = f'./fitting_parameters/{self.filename_model_I2B}'
        [loaded_model, loaded_poly] = pickle.load(open(filepath, 'rb'))

        # preprocess test vectors, st. they have correct shape for model
        input_vector_ = loaded_poly.fit_transform(current_vector.reshape((1, 3)))

        # estimate prediction of generated field
        magnetic_field_vector = loaded_model.predict(input_vector_)

        return np.round(magnetic_field_vector.reshape(3), 3)