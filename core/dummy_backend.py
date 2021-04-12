import numpy as np
import threading 
from time import sleep


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
        self._actual_currents = np.array([0, 0, 0], dtype=float)
        self._setpoint_fields = np.array([0, 0, 0], dtype=float)
        self._magnet_state = MagnetState.OFF
        self._demagnetization_flag = False

        # thread pool for ramping
        self.ramping_threads = np.empty(3, dtype = CurrentRampingThread)


    def get_currents(self) -> np.ndarray:
        """Returns currents of (dummy) power supplies.

        """
        return np.round(self._actual_currents, 3)


    def set_currents(self, values: np.ndarray):
        """Sets the currents of power supplies.

        :param values: Current values to be set.
        """
        self._setpoint_currents = values

        if self._magnet_state == MagnetState.ON:
            self.on_current_change.emit(self.get_currents())
            # self._actual_currents = self._setpoint_currents
            self._ramp_to_new_current_values(self._setpoint_currents)

        
    def enable_field(self):
        """Enables magnetic field.

        """
        self._magnet_state = MagnetState.ON
        self.on_field_status_change.emit(MagnetState.ON)
        # self._actual_currents = self._setpoint_currents

        self._ramp_to_new_current_values(self._setpoint_currents)


    def disable_field(self):
        """Disables magnetic field.

        """
        self._magnet_state = MagnetState.OFF
        self.on_field_status_change.emit(MagnetState.OFF)
        # self._actual_currents = np.array([0, 0, 0], dtype=float)
        self._ramp_to_new_current_values(np.array([0, 0, 0], dtype=float))


    def get_magnet_status(self) -> MagnetState:
        """Returns status of magnet.

        """
        return self._magnet_state

    def set_demagnetization_flag(self, flag: bool):
        """Sets the demagnetization flag.

        """
        self._demagnetization_flag = flag

    def _ramp_to_new_current_values(self, target_currents: np.ndarray, number_steps=5):
        """Ramp output current from the currently set current values to a new target value. 

        :param target_currents: Current values to be set.
        :param number_steps: Number of steps for ramping
        """
        try:
            # if threads are still running, initiate early stop by setting stop
            for thread in self.ramping_threads:
                if thread.is_alive():
                    thread.stop()

            # wait until all threads have exited 
            for thread in self.ramping_threads:
                thread.join()
        except AttributeError:
            pass

        # measure currently set output current
        initial_currents = self.get_currents()

        # initialize threads that ramp current from initial to final value
        for i in range(3):
            self.ramping_threads[i] = CurrentRampingThread(self._actual_currents, i, 
                    initial_currents[i], target_currents[i], number_steps = number_steps)

        no_running_threads_ini = threading.active_count()
        for thread in self.ramping_threads:
            thread.start()

        print(f'running threads before: {no_running_threads_ini} now: {threading.active_count()}')


class CurrentRampingThread(threading.Thread):
    """Thread class that ramps the currents stored in an array from initial to final values. 
    The class has a stop method, which invokes an early but secure termination after finishing 
    the the currently executed ramping step.  

    """
    def __init__(self, target_array : np.ndarray, channel : int, 
                    initial_value : float, target_value : float, 
                    number_steps: int = 5, *args, **kwargs):
        """
        Instance constructor.
        
        :param target_array: Array containing the actual currents. This argument is only required for the dummy backend.
        :param channel: Channel number, which is the index of target_array at which the current value should be updated.
        :param initial_value: Initial current value which is currently set
        :param target_value: Target current value which should be obtained at the end
        :param number_steps: Number of steps used for ramping.
        """
        super().__init__(*args, **kwargs)

        self._target_array = target_array
        self._channel = channel
        self._number_steps = number_steps
        self._step_size = (target_value - initial_value) / number_steps

        self._stop_event = threading.Event()

    def run(self):
        """Overwrite run method to define the thread's purpose. If a stop event is set while the thread is running, 
        the current ramping step is finalized and the thread will be terminated before starting the next ramping step. 
        """
        for _ in range(self._number_steps):
            # exit loop if stop event has been set
            if self._stop_event.is_set():
                break
            self._target_array[self._channel] += self._step_size
            sleep(1)

    def stop(self):
        """Set the stop event. 
        """
        self._stop_event.set()



