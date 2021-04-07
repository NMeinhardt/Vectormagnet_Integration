# filename: field_current_tr.py
#
# The following helper functions provide the calculation of magnetic fields and associated currents,
# using a cubic model for the relation between the current and magnetic field (and vice versa).
#
# Author: Maxwell Guerne-Kieferndorf (QZabre)
#            gmaxwell at student.ethz.ch
#
# Date: 09.10.2020
# latest update: 23.03.2021

# Standard library imports 
import pickle
import numpy as np
import pandas as pd
from sklearn import linear_model
from sklearn.preprocessing import PolynomialFeatures


def computeMagneticFieldVector(magnitude: float, theta: float, phi: float):
    """
    Compute the cartesian coordinates of a magnetic field with an arbitrary direction
    and an arbitrary magnitude, given the spherical coordinates.

    Args:
        magnitude: of the B-field, units: [mT]
        theta: polar angle, between desired field direction and z axis
        phi: azimuthal angle (angle measured counter clockwise from the x axis)

    Returns:
        Vector of 3 B field components (Bx,By,Bz), as a np.array, units: [mT]
    """

    x = np.sin(np.radians(theta)) * np.cos(np.radians(phi))
    y = np.sin(np.radians(theta)) * np.sin(np.radians(phi))
    z = np.cos(np.radians(theta))

    unitVector = np.array((x, y, z))
    unitVector = unitVector / np.linalg.norm(unitVector)

    return np.around(unitVector * magnitude, 3)


def computeCoilCurrents(B_fieldVector, 
                model_filename = r'fitting_parameters\model_QSM_poly3_nooffset_B2I.sav'):
    """
    Compute coil currents [mA] required to generate the desired magnetic field vector.
    Model derived from calibration measurements and saved as file

    Args:
    - B_fieldVector (1d-ndarray of length 3): B-field in cartesian coordinates and in mT
    - mode_filename (str): valid path of the model use to transform currents into magnetic fields

    Return: 
    - currVector (1d-ndarray of length 3): Estimated current values [A] that are required 
    to generate B_fieldVector 
    """
    # load the model from disk
    [loaded_model, loaded_poly] = pickle.load(open(model_filename, 'rb'))

    # preprocess test vectors, st. they have correct shape for model
    B_fieldVector_reshape = B_fieldVector.reshape((1, 3))
    test_vectors_ = loaded_poly.fit_transform(B_fieldVector_reshape)

    # estimate prediction of required currents
    currVector = loaded_model.predict(test_vectors_)
    currVector = currVector.reshape(3)      # [mA]
    currVector = np.round(currVector, 3)    # round to nearest milliamp

    return currVector


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


if __name__ == '__main__':
    # ------------------------Testing area--------------------------
    B2 = spherical_to_cartesian(np.array([50, 90, 90]))
    print(f'Bx = {B2[0]}mT, By = {B2[1]}mT, Bz = {B2[2]}mT')
    currents = computeCoilCurrents(B1)
    print(f'I1 = {currents[0]}A, I2 = {currents[1]}A, I3 = {currents[2]}A')
    B2 = computeMagField(currents)
    print(f'Bx = {B2[0]:.3f}mT, By = {B2[1]:.3f}mT, Bz = {B2[2]:.3f}mT')
