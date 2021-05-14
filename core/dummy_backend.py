import numpy as np
import threading 
from time import sleep
from PyQt5.QtCore import pyqtSignal
import logging 
logging.basicConfig(level=logging.DEBUG)

from core.backend_base import MagnetBackendBase, ObserverThread
from core.backend_base import MAGNET_STATE as MagnetState
from core.backend_base import CURRENT_TASK as CurrentTask


class DummyMagnetBackend(MagnetBackendBase):
    """A dummy Vector Magnet backend.
    
    """
    name = 'Dummy (unconnected)'

    # Event: A previous task has finished. 
    on_task_finished = pyqtSignal(CurrentTask)

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
        self.ramp_num_steps = 5
        self.maxCurrent = 5.05
        self.maxVoltage = 30

        # thread pool for ramping
        self.ramping_threads = np.empty(3, dtype = CurrentRampingThread)

        # catch signal emitted when a task is finished
        self.on_task_finished.connect(self.on_task_finished_action)

    def __del__(self):
        """Shut down 
        """
        logging.debug(f'BAK :: magnet ({self.name})) :: Shutdown')

    def get_currents(self) -> np.ndarray:
        """Returns currents of (dummy) power supplies.

        """
        return np.round(self._actual_currents, 3)


    def set_currents(self, values: np.ndarray):
        """Sets the currents of power supplies.

        :param values: Current values to be set.
        """
        logging.debug(f'BAK :: magnet ({self.name})) :: set_currents: {values}')
        self._setpoint_currents = values

        if self._magnet_state == MagnetState.ON:
            self.on_task_change.emit(CurrentTask.SWITCHING)
            self._ramp_to_new_current_values(self._setpoint_currents, CurrentTask.SWITCHING)

        
    def enable_field(self):
        """Enables magnetic field.

        """
        logging.debug(f'BAK :: magnet ({self.name})) :: enable_field')
        self.on_field_status_change.emit(MagnetState.ON)
        self._magnet_state = MagnetState.ON

        # ramp field from zero to the setpoint
        self._ramp_to_new_current_values(self._setpoint_currents, CurrentTask.ENABLING)


    def disable_field(self):
        """Disables magnetic field.

        """
        logging.debug(f'BAK :: magnet ({self.name})) :: disable_field')
        # change state and emit signal to notify gui layer 
        self._magnet_state = MagnetState.OFF
        self.on_field_status_change.emit(MagnetState.OFF)

        # bring currents to zero and emit signals in each step since automatic update of displayed currents is off now
        self._ramp_to_new_current_values(np.array([0, 0, 0], dtype=float), CurrentTask.DISABLING, emit_signals_flag = True)


    def get_magnet_status(self) -> MagnetState:
        """Returns status of magnet.

        """
        return self._magnet_state


    def set_demagnetization_flag(self, flag: bool):
        """Sets the demagnetization flag.

        """
        logging.debug(f'BAK :: magnet ({self.name})) :: set_demagnetization_flag: {flag}')
        self._demagnetization_flag = flag
        
        # notify UI that flag has been changed successfully 
        self.on_demagnetization_flag_change.emit(flag)

    
    def get_demagnetization_flag(self) -> bool:
        """Returns the demagnetization flag.

        """
        return self._demagnetization_flag


    def get_max_current(self) -> float:
        """Returns the maximum limit on current for dummy backend.

        """
        return self.maxCurrent


    def on_task_finished_action(self, finished_task : CurrentTask):
        """React on a finished task by emitting on_task_change signal. 
        If the finished task was to disable the magnet, additionally emit on_field_status_change signal.
        """
        logging.debug(f'BAK :: magnet ({self.name})) :: on_task_finished_action: {finished_task}')
        if finished_task == CurrentTask.DEMAGNETIZING:
            # demagnetization is done, notify UI that a new field might be set now.
            self.on_task_change.emit(CurrentTask.ENABLING)
        elif finished_task == CurrentTask.DISABLING:
            # disabling of the field is done, emit signal of status change, too
            self.on_field_status_change.emit(MagnetState.OFF)
            self.on_task_change.emit(CurrentTask.IDLE)
        else:
            # either CurrentTask.ENABLING or CurrentTask.SWITCHING is done, notify UI that nothing more happens
            self.on_task_change.emit(CurrentTask.IDLE)


    def _ramp_to_new_current_values(self, target_currents: np.ndarray, running_task : CurrentTask, emit_signals_flag = True):
        """Ramp output current from the currently set current values to a new target value. 

        :param target_currents: Current values to be set.
        :param running_task: Indicator for the purpose of ramping the currents, e.g. for enabling or disabling the field.
        :param emit_signals_flag (optional): If True the self.on_single_current_change signal is emitted after each step.
            This flag is intented to be used when disabling the magnet, since current updates should be switched off 
            when the magnet is off, but the process of driving the currents to zero should still be monitored.
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
        
        # emit signal to herald a new task
        if self._demagnetization_flag:
            self.on_task_change.emit(CurrentTask.DEMAGNETIZING)
        else:
            self.on_task_change.emit(running_task)

        # if desired, pass the on_current_change attribute to the individual threads
        if emit_signals_flag:
            signal = self.on_single_current_change
        else:
            signal = None

        # initialize threads that ramp current from initial to final value
        for i in range(3):
            self.ramping_threads[i] = CurrentRampingThread(self._actual_currents, i, target_currents[i], 
                    number_steps = self.ramp_num_steps, signal = signal,
                    demagnetization_flag = self._demagnetization_flag)

        # start the threads
        for thread in self.ramping_threads:
            thread.start()

        # start the observer of the three threads
        self.observer = ObserverThread(self.ramping_threads, running_task, self.on_task_finished, 
                    check_demagnetization = self._demagnetization_flag)
        self.observer.start()


class CurrentRampingThread(threading.Thread):
    """Thread class that ramps the currents stored in an array from initial to final values. 
    The class has a stop method, which invokes an early but secure termination after finishing 
    the currently executed ramping step.  

    """

    def __init__(self, target_array : np.ndarray, channel : int, target_value : float, 
                    signal : pyqtSignal = None, demagnetization_flag = False,
                    number_steps: int = 5, *args, **kwargs):
        """
        Instance constructor.
        
        :param target_array: Array containing the actual currents. This argument is only required for the dummy backend.
        :param channel: Channel number, which is the index of target_array at which the current value should be updated.
        :param target_value: Target current value which should be obtained at the end
        :param number_steps: Number of steps used for ramping.
        :param signal (optional): pyqtSignal to emit after each step. The signal argument must be of types (float, int).
        :param demagnetization_flag (optional): If flag is True, a demagnetization procedure is applied to the coi prior to ramping.
        """
        super().__init__(*args, **kwargs)

        # initialize variables 
        self._target_array = target_array
        self._channel = channel
        self._number_steps = number_steps
        self._target_value = target_value
        self._signal = signal
        self._demagnetization_flag = demagnetization_flag
        self._demagnetization_passed = False
        self._stop_event = threading.Event()

        # define a factor [s/A] relating sleeping duration with step size to mimic hardware's latency
        self._duration_factor = 1


    def run(self):
        """Overwrite run method to define the thread's purpose. If a stop event is set while the thread is running, 
        the current ramping step is finalized and the thread will be terminated before starting the next ramping step. 
        """
        # if desired run the demagnetization procedure first
        if self._demagnetization_flag and not np.isclose(0, self._target_array[self._channel]):
            self._demagnetization_procedure()
        self._demagnetization_passed = True

        # estimate current distance to target and set step size
        step_size = (self._target_value - self._target_array[self._channel]) / self._number_steps

        # estimate sleep duration to mimic hardware
        sleep_duration = abs(step_size) * self._duration_factor

        for _ in range(self._number_steps):
            # exit loop if stop event has been set
            if self._stop_event.is_set():
                break

            # update target array storing the currents at index given by _channel 
            self._target_array[self._channel] += step_size

            # send a signal with array of current values as arguments if provided
            if self._signal is not None:
                self._signal.emit(self._target_array[self._channel], self._channel)

            # wait for the hardware to execute the task    
            sleep(sleep_duration)


    def stop(self):
        """Set the stop event. 
        """
        self._stop_event.set()
    

    def demagnetization_completed(self) -> bool:
        """Return whether demagnetization has been completed. 
        """
        return self._demagnetization_passed


    def _demagnetization_procedure(self):
        """Apply a demagnetization procedure, which performs an approximation of a damped oscillation.
        Eventually, zero current is applied and the remnant magnetization ideally zero, too. 
        The initial amplitude is the currently applied current. 

        """   
        # initialize vertices of damped osciallation which are to be approached during the procedure
        reference_points = np.array([0.2, 1, 2, 3, 4, 5, 6, 7, 8])
        factors = np.exp(-0.7 * reference_points)

        # estimate vertices of oscillation and alternatingly flip sign of amplitude
        vertices = self._target_array[self._channel] * factors * (-1)**np.arange(1, len(factors)+1)

        # add zero at the end
        vertices = np.append(vertices, 0)

        for i in range(len(vertices)):

            step_size = (vertices[i] - self._target_array[self._channel]) / self._number_steps
            sleep_duration = abs(step_size) * self._duration_factor

            for _ in range(self._number_steps):
                # exit loop if stop event has been set
                if self._stop_event.is_set():
                    break

                # update target array storing the currents at index given by _channel 
                self._target_array[self._channel] += step_size

                # send a signal with array of current values as arguments if provided
                if self._signal is not None:
                    self._signal.emit(self._target_array[self._channel], self._channel)

                # add an artificial sleep to mimic the hardware's latency
                sleep(sleep_duration)

            # this sleep is also in hardware backend to ensure that vertex is actually approached
            sleep(0.1)

