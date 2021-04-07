# filename: current_control.py
#
# This code is meant to bundle the communication with the IT6432 current sources
# and control the current flow/change of configurations for each of the PSUs.
#
# Author: Maxwell Guerne-Kieferndorf (QZabre)
#         gmaxwell at student.ethz.ch
# Date: 13.01.2021
# latest update: 23.03.2021

import os.path as path
import sys
import threading
import traceback
from time import sleep, time
import numpy as np

try:
    from core.itech_driver import ITPowerSupplyDriver
except BaseException:
    pass
finally:
    sys.path.insert(1, path.join(sys.path[0], '..'))
    from core.itech_driver import ITPowerSupplyDriver
    from core.backend_base import MagnetBackendBase
    from core.backend_base import MAGNET_STATE as MagnetState


class ElectroMagnetBackend(MagnetBackendBase):
    """Backend for controlling the three power supplies of the VM.
    Functions for setting the current or demagnetizing the coils are wrapped by this class.

    """
    name = 'ElectroMagnet'

    def __init__(self, ramp_num_steps : int = 5):
        """Instance constructor.

        :param ramp_num_steps: number of steps when ramping currents.
  
        """

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
        self.power_supplies = np.empty(3, dtype= ITPowerSupplyDriver)
        for i in range(1,4):
            self.power_supplies[i-1] = ITPowerSupplyDriver(i,   self.IPs[i], 
                                                                self.port, 
                                                                self.maxCurrent, 
                                                                self.maxVoltage)

    @property
    def ramp_num_steps(self) -> int:
        return self._ramp_num_steps

    @ramp_num_steps.setter
    def ramp_num_steps(self, num_steps: int):
        self._ramp_num_steps = num_steps

    @property
    def setCurrentValues(self) -> list:
        return self._setpoint_currents

    @setCurrentValues.setter
    def setCurrentValues(self, currents: list):
        self._setpoint_currents = currents

    def open_connection(self):
        """Open a connection to each IT6432 current source.
        """
        for channel in self.power_supplies:
            channel.connect()
            channel.set_operation_mode('remote')

    def close_connection(self):
        """Close the connection with the current sources.
        """
        for channel in self.power_supplies:
            channel.set_operation_mode('local')
            channel.close()

    def set_currents(self, values: np.ndarray):
        """Sets the currents of power supplies.

        :param values: Current values to be set.
        """
        thread_pool = []

        signs = np.sign(values)

        for ix, power_supply in enumerate(self.power_supplies):
            des_current_ix = (signs[ix] * values[ix]
                              if abs(values[ix]) <= power_supply.current_lim
                              else power_supply.current_lim)
            # conservative estimate of coil resistance: 0.472 ohm -> ensure current compliance
            # (actual value is probably closer to 0.46)
            v_set_ix = signs[ix] * 0.48 * des_current_ix
            worker_ix = VoltageRamper(power_supply, v_set_ix, des_current_ix, self.ramp_num_steps)
            thread_pool.append(worker_ix)

        for thread in thread_pool:
            thread.start()
        for thread in thread_pool:
            thread.join()

        self._setpoint_currents = values

    def _demagnetize_coils(self, current_config: list = [1, 1, 1], steps: int = 5):
        """Eliminate hysteresis effects by applying a slowly oscillating and decaying
        (triangle wave) voltage to the coils.

        :param current_config: Initial configuration before ramping down the voltage.
        :type cmd: list, optional
        :param steps: Number of voltage increments used when ramping voltage back and forth.
        :type steps: int, optional

        """
        points = np.array([0.2, 1, 2, 3, 4, 5, 6, 7, 8])
        bounds = 0.475 * np.outer(current_config, np.exp(-0.7 * points))

        for power_supply in self.power_supplies:
            power_supply.set_current(5.01)

        thread_pool = [None, None, None]
        target_func = rampVoltageSimple
        sign = 1

        for i in range(bounds.shape[1]):
            voltages = []
            sign *= -1

            for ix, power_supply in enumerate(self.power_supplies):
                voltages.append(power_supply.get_voltage())
                kwargs_ix = {'steps': steps,
                             'set_voltage': voltages[ix], 'new_voltage': sign * bounds[ix, i]}

                thread_pool[ix] = threading.Thread(target=target_func,
                                                   name=f'VoltageRamper_{ix + 1}',
                                                   args=(power_supply,),
                                                   kwargs=kwargs_ix)

            for thread in thread_pool:
                thread.start()

            for thread in thread_pool:
                thread.join()

            sleep(0.1)

        self.disableCurrents()

    def disableCurrents(self):
        """Disable current controllers.
        """
        thread_pool = []

        for power_supply in self.power_supplies:
            worker_ix = VoltageRamper(power_supply, 0, 0, self.ramp_num_steps)
            thread_pool.append(worker_ix)

        for thread in thread_pool:
            thread.start()
        for thread in thread_pool:
            thread.join()


class VoltageRamper(threading.Thread):
    """A thread that simply runs the function rampVoltage. Enables parallel operation of
    power supplies.

    """

    def __init__(self, connection: ITPowerSupplyDriver, 
                new_voltage: float, new_current: float, steps: int):
        """
        Instance constructor.
        
        :param connection: Current source which is to be controlled
        :type connection: ITPowerSupplyDriver
        :param new_voltage: Target voltage
        :param new_current: Target current
        :param step_size: Number of steps to increase voltage. Fewer -> faster ramp
        """
        threading.Thread.__init__(self)
        self._connection = connection
        self._new_voltage = new_voltage
        self._new_current = new_current
        self._num_steps = steps

        self._name = 'VoltageRamper_' + str(self._connection.channel)

    def run(self):
        try:
            rampVoltage(
                self._connection,
                self._new_voltage,
                self._new_current,
                self._num_steps)
        except BaseException:
            print(f'There was an error on channel {self._connection.channel}!')
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            print(f'{exctype} {value}\n{traceback.format_exc()}')


def rampVoltageSimple(connection: ITPowerSupplyDriver, initial_voltage: float = 0,
                    target_voltage: float = 0.3, steps: int = 5):
    """Ramping the voltage linearly from initial to target value.

    :param connection: Current source which is to be controlled
    :type connection: ITPowerSupplyDriver
    :param initial_voltage: Voltage that is set right now.
    :param target_voltage: Target voltage.
    :param steps: Defaults to 5.
    """
    connection.set_voltage(initial_voltage)
    diff_v = target_voltage - initial_voltage
    step_size = diff_v / steps

    for _ in range(steps):
        initial_voltage = initial_voltage + step_size
        connection.set_voltage(initial_voltage)
        diff_v = target_voltage - initial_voltage

    connection.set_voltage(target_voltage)


def rampVoltage(connection: ITPowerSupplyDriver, target_voltage: float,
                target_current: float, steps: int):
    """Ramp voltage to a new specified value. The current should not be directly set due
    to the load inductance, instead it is a limiter for the voltage increase. Like this, it
    is possible to ensure that the current takes the exact desired value without causing
    the voltage protection to trip.

    :param connection:Current source which is to be controlled
    :param target_voltage: Target voltage
    :param target_current: Target current
    :param steps: number of voltage increments.
    """
    connection.clrOutputProt()

    if connection.get_output_state() == 'off':
        connection.set_voltage(0)
        connection.enable_output()

    if target_current > connection.current_lim:
        target_current = connection.current_lim
    if target_current < 0.002 or abs(target_voltage) < 0.001:
        target_current = 0.002
        target_voltage = 0
    if abs(target_voltage) > connection.voltage_lim:
        target_voltage = connection.voltage_lim

    meas_voltage = connection.get_voltage()
    meas_current = connection.get_current()

    if target_current - abs(meas_current) < 0:
        intermediate_step = 0.4 * target_current if target_current > 0.02 else 0
        rampVoltageSimple(connection, meas_voltage, intermediate_step, steps)

    repeat_count = 0
    meas_current_queue = [meas_current, 0]
    while not (abs(meas_current) < target_current or repeat_count >= 5):
        meas_current_queue.insert(0, connection.get_current())
        meas_current_queue.pop(2)
        repeat = abs(meas_current_queue[0] - meas_current_queue[1]) < 0.002
        if repeat:
            repeat_count += 1
        else:
            repeat_count = 0

    connection.set_current(target_current)

    if target_current < 0.002 or abs(target_voltage) < 0.001:
        connection.disable_output()
    else:
        meas_voltage = connection.get_voltage()
        rampVoltageSimple(connection, meas_voltage, target_voltage, steps)


if __name__ == "__main__":

    psu = ElectroMagnetBackend()

    psu.openConnection()
    # psu.setCurrents([1, 3, 2.3])

    sleep(10)

    psu.disableCurrents()

    psu.closeConnection()
