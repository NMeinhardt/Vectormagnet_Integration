
# imports
import os
from datetime import datetime
from time import sleep, time
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from core.hardware_backend import ElectroMagnetBackend
from core.backend_base import MAGNET_STATE as MagnetState
from MetrolabTHM1176 import MetrolabSensor


# define functions
def setup_test_values(maximum : float, pts_per_interval : int):
    """Generate a list of test values for a hysteresis measurement, including 
    virgin hysteresis loop in the beginning.

    :param maximum: Maximum value
    :param pts_per_interval: Number of points for each interval, i.e. of virgin hysteresis loop
    """
    # virgin hysteresis loop, decreasing and increasing branches
    test_values = np.linspace(0, maximum, pts_per_interval - 1, endpoint=False)
    test_values = np.append(test_values, np.linspace(maximum, -maximum, 2*pts_per_interval-2, endpoint=False))
    test_values = np.append(test_values, np.linspace(-maximum, maximum, 2*pts_per_interval-1, endpoint=True))

    return test_values

def save_results(directory, currents, voltages, fields_mean, fields_std, data_filename_postfix = 'measurements'):
    """Update a single label with new current values.

    """
    df = pd.DataFrame({'I [A]': currents,
                        'U [V]': voltages,
                        'mean Bx [mT]': fields_mean[:, 0],
                        'mean By [mT]': fields_mean[:, 1],
                        'mean Bz [mT]': fields_mean[:, 2],
                        'std Bx [mT]': fields_std[:, 0],
                        'std By [mT]': fields_std[:, 1],
                        'std Bz [mT]': fields_std[:, 2]})

    now = datetime.now().strftime('%y_%m_%d_%H-%M-%S')
    output_file_name = f'{now}_{data_filename_postfix}.csv'
    file_path = os.path.join(directory, output_file_name)
    df.to_csv(file_path, index=False, header=True) 


#%% 
# (1): Set up measurement
# initialize settings
ramp_num_steps = 3 
averages = 50
max_current = 5
pts_per_interval = 100
sleep_period = 2.4

# settings for saving
filename_postfix = f'hysteresis_measurement_in_assembly_coils235_{pts_per_interval}perInterval_{averages}avgs_afterDemagnetization_middle'
directory = './measurements/hysteresis_full_assembly'

# set up arrays for measurement quantities
test_currents = setup_test_values(max_current, pts_per_interval)
measured_currents = np.zeros_like(test_currents)
measured_voltages = np.zeros_like(test_currents)
measured_fields_mean = np.zeros((len(test_currents), 3))
measured_fields_std = np.zeros((len(test_currents), 3))

# initialize power supply and sensor
power_supply = ElectroMagnetBackend(ramp_num_steps = ramp_num_steps, number_channels=1)
power_supply.enable_field()
sensor = MetrolabSensor(block_size=30, range='0.3 T', period=0.01, average=1)
# sensor.calibrate()

#%% 
# (2): Run measurement and save data afterwards
for i, value in enumerate(test_currents):
    # print status
    print(f'\r {100*i/len(test_currents):2.0f} %', end='', sep='', flush=False)

    # set field
    power_supply.set_currents([value, 0, 0])
    sleep(sleep_period)

    # measure current and voltage
    measured_currents[i] = power_supply.get_currents()
    measured_voltages[i] = power_supply.power_supplies[0].get_voltage()

    # measure field
    raw_data = np.array(sensor.measureFieldArraymT(averages)).swapaxes(0, 1)
    measured_fields_mean[i] = np.average(raw_data, axis=0)
    measured_fields_std[i] = np.std(raw_data, axis=0)
print('\n')

# get remnant field at zero current 
power_supply.set_currents([5, 0, 0])
sleep(3)
raw_data = np.array(sensor.measureFieldArraymT(averages)).swapaxes(0, 1)
mean_at_end = np.average(raw_data, axis=0)
std_at_end = np.std(raw_data, axis=0)
print(mean_at_end)
print(std_at_end)

# switch off output of power supply
# power_supply.set_currents([5, 0, 0])
power_supply.set_demagnetization_flag(True)
sleep(3)
power_supply.disable_field()


# save results
save_results(directory, measured_currents, measured_voltages, 
                        measured_fields_mean, measured_fields_std, 
                        filename_postfix)


