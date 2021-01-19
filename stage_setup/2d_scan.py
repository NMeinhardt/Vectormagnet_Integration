"""
filename: 2d_scan.py

This script is meant to perform a 2d scan of the magnetic field using a single sensor,
specifically for use with the Hall Sensor cube.

Author: Nicholas Meinhardt (QZabre)
        nmeinhar@student.ethz.ch


Date: 13.10.2020
"""

# %%
########## Standard library imports ##########
import numpy as np
import serial
from time import time, sleep
import os

########## local imports ##########
try:
    from conexcc.conexcc_control import setup, reset_to
except ModuleNotFoundError:
    import sys
    sys.path.insert(1, os.path.join(sys.path[0], '..'))
finally:
    from conexcc.conexcc_control import setup, reset_to
    from calibration import grid_2D
    from MetrolabTHM1176.thm1176 import MetrolabTHM1176Node
    from main_comm_new import *

# %%
# set measurement parameters and folder name
sampling_size = 15 # number of measurements per sensor for averaging

directory = r'C:\Users\Magnebotix\Desktop\Qzabre_Vector_Magnet\1_Version_2_Vector_Magnet\1_data_analysis_interpolation\Data_Analysis_For_VM\data_sets\2d_scans_different_fields\set7'

# number of grid points per dimension
grid_number = 20

# %%
# initialize actuators
init_pos = np.array([5, 3, 1.3])
# ports for Magnebotix PC
COM_ports = ['COM4', 'COM5', 'COM6']
CC_X, CC_Y, CC_Z = setup(init_pos, COM_ports=COM_ports)


# %%
# manually adjust stage position
# z_offset = 8.3
# new_pos = 
# _ = reset_to(new_pos, CC_X, CC2=CC_Y, CC3=CC_Z)


# %%
# set the bounds for x and y that are used for the scan
limits_x = [5, 9]
limits_y = [3, 9]

# set the bounds for x and y that are used for the scan, relative to mid position
# mid = [7.8866, 0.0166]
# distance = 2
# limits_x = [mid[0] - distance, mid[0] + distance]
# limits_y = [0, 4]
# set currents in coils
currentConfig = [0,0,1]
# integer value, mA
currentStrength = 2000

desCurr = []
for i in range(len(currentConfig)):
        desCurr.append(currentStrength * currentConfig[i])
print(f'the currents are: {desCurr[0]} mA, {desCurr[1]} mA, {desCurr[2]} mA')

channel_1 = IT6432Connection(1)
channel_2 = IT6432Connection(2)
channel_3 = IT6432Connection(3)
openConnection(channel_1, channel_2, channel_3)
# demagnetizeCoils()
sleep(0.3)
setCurrents(channel_1, channel_2, channel_3, desCurr)

#%%
# perform actual 2d scan
# with MetrolabTHM1176Node(block_size=30, period=0.01, range='0.3 T', average=1) as node:
node = MetrolabTHM1176Node(block_size=30, period=0.01, range='0.1 T', average=1)

filename_suffix = f'2d_scan_({currentConfig[0]}_{currentConfig[1]}_{currentConfig[2]})'
positions_corrected, B_field, filepath = grid_2D(CC_X, CC_Y, node, 1.3, xlim=limits_x, ylim=limits_y, grid_number=grid_number,
                                                     sampling_size=sampling_size, save_data=True,suffix=filename_suffix, directory=directory)
disableCurrents(channel_1, channel_2, channel_3)

closeConnection(channel_1)
closeConnection(channel_2)
closeConnection(channel_3)

#%%
# this part uses the Calibration Cube as Sensor
# --------------------------------------------------------------------

# # initialize sensor
# specific_sensor = 55
# port_sensor = 'COM4'

# # establish permanent connection to calibration cube: open serial port; baud rate = 256000
# with serial.Serial(port_sensor, 256000, timeout=2) as cube:

#     positions_corrected, B_field, filepath = grid_2D_cube(CC_X, CC_Y, cube, specific_sensor, z_offset, 
#                                       xlim=limits_x, ylim=limits_y, grid_number=grid_number,
#                                       sampling_size=sampling_size, save_data=True, directory=directory)

