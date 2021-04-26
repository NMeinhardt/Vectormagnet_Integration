import threading
import numpy as np
from time import sleep
from PyQt5.QtCore import pyqtSignal

from core.itech_driver import ITPowerSupplyDriver, OutputState
from core.backend_base import MagnetBackendBase
from core.backend_base import MAGNET_STATE as MagnetState


class ElectroMagnetBackend(MagnetBackendBase):
    """Backend for controlling the three power supplies of the VM.
    Functions for setting the current or demagnetizing the coils are wrapped by this class.

    """
    name = 'ElectroMagnet'

    def __init__(self, ramp_num_steps : int = 5, number_channels = 3):
        """Instance constructor.

        :param ramp_num_steps: number of steps when ramping currents.
        """
        super().__init__()

        # Initialise state.
        self._setpoint_currents = np.array([0, 0, 0], dtype=float)
        self._setpoint_fields = np.array([0, 0, 0], dtype=float)
        self._magnet_state = MagnetState.OFF
        self._demagnetization_flag = False

        # changeable parameters
        self._ramp_num_steps = ramp_num_steps
        self.maxCurrent = 5.05
        self.maxVoltage = 30
        self.port = 30000
        self.IPs = ['192.168.237.47', '192.168.237.48', '192.168.237.49']

        # connect to power supplies
        self.power_supplies = np.empty(number_channels, dtype= ITPowerSupplyDriver)
        for i in range(3):
            self.power_supplies[i] = ITPowerSupplyDriver(i,   self.IPs[i], 
                                                                self.port, 
                                                                self.maxCurrent, 
                                                                self.maxVoltage)

        # thread pool for ramping
        self.ramping_threads = np.empty(number_channels, dtype = CurrentRampingHardwareThread)

        # open connection to power supplies
        self.open_connection()

    @property
    def ramp_num_steps(self) -> int:
        return self._ramp_num_steps

    @ramp_num_steps.setter
    def ramp_num_steps(self, num_steps: int):
        self._ramp_num_steps = num_steps

    def shutdown(self):
        """Overwrite method that is executed when changing backend or closing QS3.
        """
        print(f"BAK :: magnet ({self.name}) :: shutdown")
        if self._magnet_state == MagnetState.ON:
            # enforce that no demagnetization happens when window is suddenly closed
            self._demagnetization_flag = False
            self.disable_field()

            # wait until all threads have exited, else threads will run into errors after disconnecting 
            for thread in self.ramping_threads:
                thread.join()

        # disconnect from power supplies
        self.close_connection()


    def open_connection(self):
        """Open a connection to each IT6432 current source.
        """
        print(f"BAK :: magnet ({self.name}) :: open_connection")
        for channel in self.power_supplies:
            channel.connect()
            channel.set_operation_mode('remote')
            if channel.get_output_state() == OutputState.ON:
                channel.disable_output()
    
    
    def close_connection(self):
        """Close the connection with the current sources.
        """
        print(f"BAK :: magnet ({self.name}) :: close_connection")
        for channel in self.power_supplies:
            if channel.get_output_state() == OutputState.ON:
                channel.disable_output()
            channel.set_operation_mode('local')
            channel.close() 
            
    def get_currents(self) -> np.ndarray:
        """Returns measured currents of power supplies.

        """
        if self._magnet_state == MagnetState.ON:
            currents = np.array([self.power_supplies[i].get_current() for i in range(3)])
        else:
            currents = np.zeros(3)
        
        return np.round(currents, 3)


    def set_currents(self, values: np.ndarray):
        """Sets the currents of power supplies.

        :param values: Current values to be set.
        """
        self._setpoint_currents = values

        if self._magnet_state == MagnetState.ON:
            self._ramp_to_new_current_values(self._setpoint_currents)
            

    def enable_field(self):
        """Enables magnetic field.
        """
        # ramp to setpoint currents, note that demagnetization and enabling of outputs are handled implicitly
        self._ramp_to_new_current_values(self._setpoint_currents)
        
        self._magnet_state = MagnetState.ON
        self.on_field_status_change.emit(MagnetState.ON)


    def disable_field(self):
        """Disables magnetic field.
        """
        # ramp currents down to zero, note that demagnetization is handled implicitly
        self._ramp_to_new_current_values(np.zeros(3, dtype=float), emit_signals_flag=True)

        # disable outputs of current supplies
        [self.power_supplies[i].disable_output() for i in range(3)]

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


    def _ramp_to_new_current_values(self, target_currents: np.ndarray, emit_signals_flag = False):
        """Ramp output current from the currently set current values to a new target value. 

        :param target_currents: Current values to be set.
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
        
        # if desired, pass the on_single_current_change attribute to the individual threads
        if emit_signals_flag:
            signal = self.on_single_current_change
        else:
            signal = None

        # initialize threads that ramp current from initial to final value
        for i in range(3):
            self.ramping_threads[i] = CurrentRampingHardwareThread(self.power_supplies[i], target_currents[i], 
                                            number_steps = self.ramp_num_steps, signal=signal,
                                            demagnetization_flag = self._demagnetization_flag)

        # start the threads
        for thread in self.ramping_threads:
            thread.start()



class CurrentRampingHardwareThread(threading.Thread):
    """Thread class that ramps the output current of a single power supply from an initial to 
    the provided final value. The class has a stop method, which invokes an early but secure termination 
    after finishing the currently executed ramping step.  

    """
    def __init__(self, device : ITPowerSupplyDriver, target_current : float, 
                    signal : pyqtSignal = None, demagnetization_flag = False,
                    number_steps: int = 5, *args, **kwargs):
        """
        Instance constructor.
        
        :param device: driver for respective power supply
        :param number_steps (optional): Number of steps used for ramping.
        :param signal (optional): pyqtSignal to emit after each step. The signal argument must be of type np.array.
        :param demagnetization_flag (optional): If flag is True, a demagnetization procedure is applied to the coi prior to ramping.
        """
        super().__init__(*args, **kwargs)

        # initialize variables 
        self.device = device
        self.number_steps = number_steps
        self._signal = signal
        self._demagnetization_flag = demagnetization_flag
        self._stop_event = threading.Event()

        # for ensuring either current or voltage compliance, either an overestimated or underestimated voltage is required,
        # hence two estimates of the coil's resistance are defined here
        self.R_coils_overestimate = 0.62 # [Ohm]
        self.R_coils_underestimate = 0.4 # [Ohm]

        # save target current as positive number and pass its original sign to the estimated voltage.
        # use overestimate of resistance to ensure current compliance here
        self.target_current = abs(target_current)
        self.target_voltage = np.sign(target_current) * self.R_coils_overestimate * target_current
        # print(f'(ch {self.device._channel}): target is {self.target_current} A, {self.target_voltage} V')

        # check target current and voltage values, redefine if they are outside the allowed limits
        self._check_values()


    def _check_values(self):
        """Check whether target current and voltage are within the allowed limits, if not set to limits.
        """
        # check for too large value
        if self.target_current > self.device.current_lim:
            self.target_current = self.device.current_lim
            print('target current exdeeds limit')
        if abs(self.target_voltage) > self.device.voltage_lim:
            self.target_voltage = self.device.voltage_lim
            print('target voltage exdeeds limit')

        # if target is close to zero current or voltage, set to minimum values accepted by driver
        if self.target_current < 0.002 or abs(self.target_voltage) < 0.001:
            self.target_current = 0.002
            self.target_voltage = 0


    def stop(self):
        """Set the stop event. 
        """
        self._stop_event.set()


    def run(self):
        """Overwrite run method to define the thread's purpose. If a stop event is set while the thread is running, 
        the current ramping step is finalized and the thread will be terminated before starting the next ramping step. 
        """
        # clear output of device in case it has been locked due to some previous error
        self.device.clrOutputProt()

        # if the output is currently off, set voltage limit to zero before enabling output
        if self.device.get_output_state() == OutputState.OFF:
            self.device.set_voltage(0)
            self.device.enable_output()

        # measure the current output
        initial_current = self.device.get_current()

        # if desired run the demagnetization procedure first
        if self._demagnetization_flag and not np.isclose(0, initial_current, atol=0.01):
            self._demagnetization_procedure()
        
        # ensure device works in voltage compliance, take an intermediate step if this isn't the case yet
        self._ensure_voltage_compliance(initial_current)

        # only proceed if the stop has not been set already
        if not self._stop_event.is_set():

            # set current limit to target value, note that this should not influence output due to voltage compliance
            self.device.set_current(self.target_current)

            # if target current or voltage are set to zero (or smallest possible value) disable the output 
            if self.target_current <= 0.002 or abs(self.target_voltage) < 0.001:
                self.device.disable_output()

            # else ramp to lift the voltage to target_voltage, which is slightly overestimated 
            # -> once the target current is reached the device is back to current compliance
            else:
                self._linarly_ramp_voltage(self.target_voltage)


    def _ensure_voltage_compliance(self, initial_current : float):
        """Ensure that power supplies works in voltage compliance afterwards. 

        :param initial_current: measured current when calling this method. The only reason why this argument
            is added is that the current is measured in the self.run method right before calling this method,
            so measuring the current again would be an unnecessay repetition. 
        """
        # if target current is below initial current (absolute numbers), bring voltage down to slightly below the target voltage first
        if self.target_current  < abs(initial_current):
            # ramp voltage below target voltage by taking an intermediate step
            intermediate_voltage = self.R_coils_underestimate * self.target_current if self.target_current > 0.02 else 0
            self._linarly_ramp_voltage(intermediate_voltage)

        # only proceed if the stop has not been set already
        if not self._stop_event.is_set():

            # wait until target_current > currently_set_current is indeed satisfied, it may take a moment for the hardware to respond
            repeat_count = 0
            meas_current_queue = [self.device.get_current(), 0]
            while  self.target_current <= abs(meas_current_queue[0]) and repeat_count < 5:
                meas_current_queue.insert(0, self.device.get_current())
                meas_current_queue.pop(2)
                if abs(meas_current_queue[0] - meas_current_queue[1]) < 0.002:
                    repeat_count += 1
                else:
                    repeat_count = 0


    def _linarly_ramp_voltage(self, target_voltage : float):
        """Ramp the voltage of the power supply to a provided target value.
        It is recommended to only call this function when device is in voltage compliance.

        :param target_voltage: desired final voltage
        """
        # set voltage to the current output voltage (ensures voltage compliance)
        initial_voltage = self.device.get_voltage()
        self.device.set_voltage(initial_voltage)
        
        # estimate current distance to target and set step size
        step_size = (target_voltage - initial_voltage) / self.number_steps

        for i in range(self.number_steps):
            # exit loop if stop event has been set and set current to the currently measured value
            if self._stop_event.is_set():
                self.device.set_current(self.device.get_current())
                break
            
            # raise voltage by one step
            self.device.set_voltage(initial_voltage + (i+1)*step_size)

            # send a signal with array of current values as arguments if provided
            if self._signal is not None:
                self._signal.emit(self.device.get_current(), self.device._channel)

        
    def _demagnetization_procedure(self):
        """Apply a demagnetization procedure, which performs an approximation of a damped oscillation.
        Eventually, zero current is applied and the remnant magnetization ideally zero, too. 
        The initial amplitude is the currently applied current. 

        """   
        # initialize vertices of damped osciallation which are to be approached during the procedure
        reference_points = np.array([0.2, 1, 2, 3, 4, 5, 6, 7, 8])
        factors = np.exp(-0.7 * reference_points)

        # set current to max, st. power supply works in voltage compliance
        self.device.set_current(5.01)

        # measure currently set output current
        initial_current = self.device.get_current()

        # estimate vertices of oscillation and alternatingly flip sign of amplitude, add zero at the end
        vertices = initial_current * factors * (-1)**np.arange(1, len(factors)+1)
        vertices = np.append(vertices, 0)

        for i in range(len(vertices)):

            # exit loop if stop event has been set
            if self._stop_event.is_set():
                break

            # ramp to next vertex
            self._linarly_ramp_voltage(vertices[i])

            # ensure that vertex is actually approached
            sleep(0.1)



if __name__ == "__main__":

    psu = ElectroMagnetBackend()

    psu.openConnection()
    # psu.set_currents([1, 3, 2.3])

    sleep(10)

    psu.disable_field()

    psu.closeConnection()
