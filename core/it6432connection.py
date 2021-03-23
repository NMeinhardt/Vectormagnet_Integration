# filename: it6432_connection.py
#
# Class for communication with IT6432 power supplies
#
# Author: Maxwell Guerne-Kieferndorf (with QZabre)
#         gmaxwell at student.ethz.ch
#
# Date: 15.01.2021
# latest update: 09.02.2021

import socket
from time import sleep, time


class ErrorBase(Exception):
    def __init__(self, code, *args, **kwargs):
        self.code = code
        keys = kwargs.keys()
        if 'msg' in keys:
            self.msg = kwargs['msg']
        super().__init__(*args)


class GenericError(ErrorBase):
    """
    Any errors that have not yet been encountered.
    """

    def __init__(self, code, msg, *args, **kwargs):
        ErrorBase.__init__(self, code, *args, msg=msg, **kwargs)
        # logger.debug(f'{code}: {msg}')
        print(f'\n{code}: {msg}')


class ParameterOverflow(ErrorBase):
    pass


class WrongUnitsForParam(ErrorBase):
    pass


class ParamTypeError(ErrorBase):
    pass


class InvalidCommand(ErrorBase):
    pass


class ExecutionError(ErrorBase):
    pass


class ErrorQueueOverrun(ErrorBase):
    pass


class SyntaxErrorSCPI(ErrorBase):
    pass


class InvalidCharacter(ErrorBase):
    pass


class StringDataError(ErrorBase):
    pass


class FrontPanelTimeout(ErrorBase):
    pass


class IT6432Connection:
    """
    An interface for communication with IT 6432 current sources.
    The IP address/source port can be changed by reprogramming the devices, although there
    should be no need to do this.

    Args:
            channel (int): Only use channels 1,2,3!
    """
    ##########     Connection parameters      ##########
    ########## (as configured on each device) ##########
    IT6432_ADDRESS1 = "192.168.237.47"
    IT6432_ADDRESS2 = "192.168.237.48"
    IT6432_ADDRESS3 = "192.168.237.49"
    IT6432_PORT = 30000

    @staticmethod
    def _ErrorFactory(code, msg=''):
        """
        Generate Python errors based on IT6432 error codes.

        Args:
            code (int): The error code
            msg (str, optional): The error message, only included
                                 if the error code is unknown.
                                 Defaults to ''.

        Returns:
            some subclass of Exception
        """
        errorClasses = {
            120: ParameterOverflow,
            130: WrongUnitsForParam,
            140: ParamTypeError,
            170: InvalidCommand,
            224: FrontPanelTimeout,
            -101: InvalidCharacter,
            -102: SyntaxErrorSCPI,
            -150: StringDataError,
            -200: ExecutionError,
            -350: ErrorQueueOverrun
        }

        errorClass = None
        if code in errorClasses.keys():
            errorClass = errorClasses[code]
            return errorClass(code)

        else:
            return GenericError(code, msg)

    def __init__(self, channel: int):
        self.__channel = channel
        self.__connected = False

        self._sock = socket.socket()
        self._host = '0.0.0.0'
        self._port = 0

        self._read_termination = '\n'
        self._chunk_size = 1024

        self._timeout = 5.0
        # current/voltage limits
        self.MAX_CURR = 5.05
        self.MAX_VOLT = 30
        self.current_lim = 0
        self.voltage_lim = 0

    #-----------------------------------------------------#
    #------------------ Basic functions ------------------#
    #-----------------------------------------------------#

    def connect(self):
        """
        Connects to the server, i.e. the device
        """
        try:
            if self.__channel == 1:
                self._host = self.IT6432_ADDRESS1
            elif self.__channel == 2:
                self._host = self.IT6432_ADDRESS2
            elif self.__channel == 3:
                self._host = self.IT6432_ADDRESS3
            self._port = self.IT6432_PORT

            self._sock.connect((self._host, self._port))
            self.__connected = True
            self._sock.settimeout(self._timeout)

            limits = self.getMaxMinOutput()
            self.current_lim = limits[0]
            self.voltage_lim = limits[2]

        except Exception as exc:
            # logger.error(f'A problem occured while trying to connect to channel
            # {self.__channel}: {exc}')
            print(f'A problem occured while trying to connect to channel {self.__channel}: {exc}')

    @property
    def channel(self) -> int:
        """
        return the channel that this current source is
        """
        return self.__channel

    @property
    def connected(self) -> int:
        """
        return the channel that this current source is
        """
        return self.__connected

    def _write(self, cmd: str, check_error: bool = True):
        """
        Writes command as ascii characters to the instrument.
        If there is an error, it is saved to the log.

        Args:
            cmd (str): an SCPI command
            check_error (bool, optional): Defaults to True.

        Raises:
            BaseException: if check_error is true and an error occurred.
        """
        # add command termination
        cmd += self._read_termination
        try:
            self._sock.sendall(cmd.encode('ascii'))
        except (ConnectionResetError, ConnectionError, ConnectionRefusedError, ConnectionAbortedError):
            # logger.error(f'{__name__} error when sending the "{cmd}" command')
            print(f'{__name__} error when sending the "{cmd}" command')

        if check_error:
            self.checkError()

    def _read(self, chunk_size: int = 0, check_error: bool = True) -> str:
        """
        Reads message sent from the instrument on the connection. One chunk (1024 bytes) at
        a time.

        Args:
            chunk_size (int, optional): expected chunk size to be received. Defaults to 0.
            check_error (bool, optional): Defaults to True.

        Raises:
            BaseException: if check_error is true and an error occurred.

        Returns:
            str: the decoded (from ascii) received message
        """
        read_len = 0
        chunk = bytes()
        __chunk_size = chunk_size if chunk_size != 0 else self._chunk_size

        try:
            while True:
                to_read_len = __chunk_size - read_len
                if to_read_len <= 0:
                    break
                data = self._sock.recv(to_read_len)
                chunk += data
                read_len += len(data)
                term_char = self._read_termination.encode()
                if term_char in data:
                    term_char_ix = data.index(term_char)
                    read_len = term_char_ix + 1
                    break
                else:
                    pass

        except socket.timeout:
            # logger.debug(f'{__name__} Timeout occurred!')
            print(f'{__name__} Timeout occurred! on {self.__channel}')
            return ''

        try:
            res = chunk.decode('ascii').strip('\n')
        except UnicodeDecodeError:
            res = chunk.decode('uft8').strip('\n')
            # logger.error(f'{__name__} Non-ascii string received: {res}')
            print(f'{__name__} Non-ascii string received: {res}')

        if check_error:
            self.checkError()

        return res

    def query(self, cmd: str, check_error: bool = True) -> str:
        """
        query the current source with any command

        Args:
            cmd (str): an SCPI command
            check_error (bool, optional): Defaults to True.

        Raises:
            BaseException: if check_error is true and an error occurred.

        Returns:
            str: the answer from the device
        """
        result = None
        self._write(cmd, check_error=False)
        sleep(0.1)
        result = self._read(check_error=False)
        if check_error:
            self.checkError()

        return result

    def checkError(self) -> None:
        """
        Check if an error occurred.

        Raises:
            self._ErrorFactory:
        Returns:
            Exception: See ErrorFactory
        """
        error_code, error_message = self.query('system:error?', check_error=False).split(',')
        if int(error_code) != 0 and int(error_code) != 224:
            # logger.debug(f'{__name__}; error code: {error_code}')
            raise self._ErrorFactory(int(error_code), error_message)

    def idn(self) -> str:
        """returns the device identification information."""
        return self.query('*IDN?').strip('\n')

    def clrOutputProt(self):
        """If output protection was triggered for some reason, clear it."""
        self._write('output:protection:clear')

    def clrErrorQueue(self):
        """Clear all errors from the instrument error queue"""
        self._write('system:clear')

    def saveSetup(self, n: int):
        """
        Save current source configuration settings

        Args:
            n (int): 0-100
        """
        self._write(f'*SAV {n}')

    def recallSetup(self, n: int):
        """
        Recall a saved current source configuration

        Args:
            n (int): 0-100
        """
        self._write(f'*RCL {n}')

    def close(self):
        """Closes the socket connection"""
        self._sock.close()

    # context manager

    # def __enter__(self):
    #     if not self.__connected:
    #         self.connect()
    #     return self

    # def __exit__(self, type, value, traceback):
    #     if self.__connected:
    #         self._sock.close()
    #         return not self.__connected
    #     else:
    #         return isinstance(value, TypeError)

    #-------------------------------------------------------#
    #------------------ Utility functions ------------------#
    #-------------------------------------------------------#

    def getMaxMinOutput(self) -> tuple:
        """
        Get maximum/minimum current/voltage values for each current channel.

        Returns:
            float tuple: maximum, minimum current, maximum, minimum voltage
        """
        max_curr = self.query('current:maxset?')
        max_volt = self.query('voltage:maxset?')
        min_curr = self.query('current:minset?')
        min_volt = self.query('voltage:minset?')

        return float(max_curr), float(min_curr), float(max_volt), float(min_volt)

    def getStatus(self) -> dict:
        """
        gets the current status of the current source by sending a query
        for the different status registers. For low-level debugging.

        Returns:
            dict: messages corresponding to any of the bits which were set.
        """
        messages = {}

        status = int(self.query('*STB?'))
        # status byte
        if status and 0b10000000:
            messages['STB7'] = 'An operation event has occurred.'
        if status and 0b01000000:
            messages['STB6'] = 'Master status/Request service.'
        if status and 0b00100000:
            messages['STB5'] = 'An enabled standard event has occurred.'
        if status and 0b00010000:
            messages['STB4'] = 'The output queue contains data.'
        if status and 0b00001000:
            messages['STB3'] = 'An enabled questionable event has occurred.'

        status = int(self.query('*ESR?'))
        # standard event status
        if status and 0b10000000:
            messages['ESR7'] = 'Power supply was reset.'
        if status and 0b00100000:
            messages['ESR5'] = 'Command syntax or semantic error.'
        if status and 0b00010000:
            messages['ESR4'] = 'Parameter overflows or the condition is not right.'
        if status and 0b00001000:
            messages['ESR3'] = 'Device dependent error.'
        if status and 0b00000100:
            messages['ESR2'] = 'Data of output array is missing.'
        if status and 0b00000001:
            messages['ESR0'] = 'An operation completed.'

        status = int(self.query('status:questionable:condition?'))
        # questionable event status
        if status and 0b01000000:
            messages['QER6'] = 'Overload current is set.'
        if status and 0b00100000:
            messages['QER5'] = 'Output disabled.'
        if status and 0b00010000:
            messages['QER4'] = 'Abnormal voltage output.'
        if status and 0b00001000:
            messages['QER3'] = 'Over temperature tripped.'
        if status and 0b00000100:
            messages['QER2'] = 'A front panel key was pressed.'
        if status and 0b00000010:
            messages['QER1'] = 'Over current protection tripped.'
        if status and 0b00000001:
            messages['QER0'] = 'Over voltage protection tripped.'

        status = int(self.query('status:operation:condition?'))
        # operation status
        if status and 0b10000000:
            messages['OSR7'] = 'Battery running status.'
        if status and 0b01000000:
            messages['OSR6'] = 'Negative constant current mode.'
        if status and 0b00100000:
            messages['OSR5'] = 'Constant current mode.'
        if status and 0b00010000:
            messages['OSR4'] = 'Constant voltage mode.'
        if status and 0b00001000:
            messages['OSR3'] = 'Output status on.'
        if status and 0b00000100:
            messages['OSR2'] = 'Waiting for trigger.'
        if status and 0b00000010:
            messages['OSR1'] = 'There is an Error.'
        if status and 0b00000001:
            messages['OSR0'] = 'Calibrating.'

        return messages

    def getMeasurement(self, meas_type: str = "",
                       meas_quantity: str = "current") -> float:
        """
        Get DC current/power/voltage values from this channel

        Args:
            meas_type (str, optional): Any of the types {"", "acdc", "max", "min"}. These are either
                                       a DC measurement, an RMS value or minimum/maximum.
                                       Defaults to "".
            meas_quantity (str, optional): Any of the types {"current", "voltage", "power"}.
                                           Defaults to "current".

        Returns:
            float: measured current
        """
        command = "measure:"
        quantities = ["current", "voltage", "power"]
        types = ["", "acdc", "max", "min"]
        if meas_quantity not in quantities:
            meas_quantity = "current"
        if meas_type not in types:
            meas_type = ""

        command += meas_quantity
        if meas_type != "":
            command += ":" + meas_type[0]
        command += "?"

        res = self.query(command)
        if isinstance(res, list):
            res = res[0]

        return float(res)

    def outputInfo(self) -> str:
        """
        Returns: output type (high or low capacitance) and relay mode (high impedance) and output speed.
        """
        output_type = self.query('output:type?')
        output_mode = self.query('output:relay:mode?')
        output_speed = self.query('output:speed?')
        res = 'type: ' + output_type + '; mode: ' + output_mode + '; speed: ' + output_speed

        return res

    def setMaxCurrVolt(
            self,
            current_lim: float = 5,
            voltage_lim: float = 10,
            verbose: bool = False):
        """
        Set maximum current values for each ECB channel, as long as they are under the threshold specified in the API source code.

        Args:
            current_lim (float, optional): desired maximum current. Defaults to 5.
            voltage_lim (float, optional): desired maximum voltage. Defaults to 10.
            verbose (bool, optional): print debug messages. Defaults to False.
        """
        if current_lim > self.MAX_CURR:
            self.current_lim = self.MAX_CURR
            if verbose:
                print('Current limit cannot be higher than 5.05A')
                # logger.debug('Current limit cannot be higher than 5.05A')
        else:
            self.current_lim = current_lim
        if voltage_lim > self.MAX_VOLT:
            self.voltage_lim = self.MAX_VOLT
            if verbose:
                print('Voltage cannot be higher than 30V')
                # logger.debug('Voltage limit cannot be higher than 30V')
        else:
            self.voltage_lim = voltage_lim

        self._write('current:limit:state ON;:voltage:limit:state ON')
        self._write(f'current:limit {self.current_lim};:voltage:limit {self.voltage_lim}')

    def setOutputSpeed(self, mode: str = 'normal', time: float = 1):
        """
        Set the reaction speed of the output.

        Args:
            mode (str, optional): normal, fast or time. Defaults to 'normal'.
            time (float, optional): 0.001 - 86400s, only in time mode. Defaults to 1.
        """
        modes = ['normal', 'fast', 'time']
        basecmd = 'output:speed'

        if mode not in modes:
            return

        self._write(f'{basecmd} {mode}')
        if mode == 'time':
            self._write(f'{basecmd}:time {time}')
