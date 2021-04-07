import numpy as np


from core.backend_base import MagnetBackendBase
from core.backend_base import MAGNET_STATE as MagnetState


class DummyMagnetBackend(MagnetBackendBase):
    """A dummy Vector Magnet backend.
    
    """
    name = 'Dummy (unconnected)'

    def __init__(self):
        """Instance constructor.
        """
        super().__init__()

        # Initialise state.
        self._setpoint_currents = np.array([0, 0, 0], dtype=float)
        self._setpoint_fields = np.array([0, 0, 0], dtype=float)
        self._magnet_state = MagnetState.OFF
        self._demagnetization_flag = False


    def get_currents(self) -> np.ndarray:
        """Returns currents of (dummy) power supplies.

        """
        if self._magnet_state == MagnetState.ON:
            return self._setpoint_currents
        else:
            return np.zeros(3)


    def set_currents(self, values: np.ndarray):
        """Sets the currents of power supplies.

        :param values: Current values to be set.
        """
        self._setpoint_currents = values
        self.on_current_change.emit(self.get_currents())

        
    def enable_field(self):
        """Enables magnetic field.

        """
        self._magnet_state = MagnetState.ON
        self.on_field_status_change.emit(MagnetState.ON)


    def disable_field(self):
        """Disables magnetic field.

        """
        self._magnet_state = MagnetState.OFF
        self.on_field_status_change.emit(MagnetState.OFF)


    def get_magnet_status(self) -> MagnetState:
        """Returns status of magnet.

        """
        return self._magnet_state

    def set_demagnetization_flag(self, flag: bool):
        """Sets the demagnetization flag.

        """
        self._demagnetization_flag = flag

    

    


