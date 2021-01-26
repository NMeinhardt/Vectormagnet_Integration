# filename: it6432_connection.py
#
# Class for communication with IT6432 power supplies
#
# Author: Maxwell Guerne-Kieferndorf (with QZabre)
#         gmaxwell at student.ethz.ch
#
# Date: 15.01.2021
# latest update: 25.01.2021

import socket
from time import time, sleep
# from qs3.utils import logger


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
        print(f'{code}: {msg}')


class ParameterOverflow(ErrorBase):
    pass


class WrongUnitsForParam(ErrorBase):
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


class IT6432Connection:
    """
    Quick and dirty protocol for communication with IT 6432 current sources.
    The IP address/source port can be changed by reprogramming, although there
    should be no need to do this.
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
            170: InvalidCommand,
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
        """
        Args:
            channel (int): Only use channels 1,2,3!
        """
        self.sock = socket.socket()
        self._channel = channel
        self.host = '0.0.0.0'
        self.port = 0
        self.connected = False

        self.read_termination = '\n'
        self._chunk_size = 1024

        self._timeout = 5.0
        # current/voltage limits
        self.MAX_CURR = 5.05
        self.MAX_VOLT = 30
        self.currentLim = 0
        self.voltageLim = 0

    #-----------------------------------------------------#
    #------------------ Basic functions ------------------#
    #-----------------------------------------------------#

    def connect(self) -> None:
        """
        Connects to the server, i.e. the device
        """
        try:
            if self._channel == 1:
                self.host = self.IT6432_ADDRESS1
            elif self._channel == 2:
                self.host = self.IT6432_ADDRESS2
            elif self._channel == 3:
                self.host = self.IT6432_ADDRESS3
            self.port = self.IT6432_PORT
            self.sock.connect((self.host, self.port))
            self.connected = True
            self.sock.settimeout(self._timeout)

            limits = self.getMaxMinOutput()
            self.currentLim = limits[0]
            self.voltageLim = limits[2]

        except Exception as exc:
            # logger.debug(f'A problem occured while trying to connect to channel {self._channel}: {exc}')
            print(f'A problem occured while trying to connect to channel {self._channel}: {exc}')

    def channel(self) -> int:
        """
        return the channel that this current source is
        """
        return self._channel

    def _write(self, cmd: str, check_error=True) -> None:
        """
        Writes command as string to the instrument.
        If there is an error, it is saved to the log.
        """
        # add command termination
        cmd += self.read_termination
        try:
            self.sock.sendall(cmd.encode('ascii'))
        except (ConnectionResetError, ConnectionError, ConnectionRefusedError, ConnectionAbortedError):
            # logger.debug(f'{__name__} error when sending the "{cmd}" command')
            print(f'{__name__} error when sending the "{cmd}" command')

        if check_error:
            self.checkError()

    def _read(self, chunk_size=None, check_error=True) -> str:
        """
        Reads message sent from the instrument on the connection. One chunk (1024 bytes) at
        a time.

        Args:
            chunk_size (int, optional): expected chunk size to be received. Defaults to None.
            check_error (bool, optional): Whether to actively check for system errors. Defaults to True.

        Returns:
            str: the decoded (from ascii) received message
        """
        term_char_detected = False
        read_len = 0
        chunk = bytes()
        _chunk_size = chunk_size if chunk_size is not None else self._chunk_size

        try:
            while True:
                to_read_len = _chunk_size - read_len
                if to_read_len <= 0:
                    break
                data = self.sock.recv(to_read_len)
                chunk += data
                read_len += len(data)
                term_char = self.read_termination.encode()
                if term_char in data:
                    term_char_ix = data.index(term_char)
                    read_len = term_char_ix + 1
                    term_char_detected = True
                    break
                else:
                    pass

        except socket.timeout:
            # logger.debug(f'{__name__} Timeout occurred!')
            print(f'{__name__} Timeout occurred! on {self._channel}')
            return ''

        try:
            res = chunk.decode('ascii').strip('\n')
        except UnicodeDecodeError:
            res = chunk.decode('uft8').strip('\n')
            # logger.debug(f'{__name__} Non-ascii string received: {res}')
            print(f'{__name__} Non-ascii string received: {res}')

        if check_error:
            self.checkError()

        return res

    def query(self, cmd: str, check_error=True) -> str:
        """
        query the current source with any command

        Args:
            cmd (str): an SCPI command
            check_error (bool):

        Returns:
            str: the answer from the device
        """
        # more = False
        result = None
        self._write(cmd, check_error=False)
        sleep(0.1)
        result = self._read(check_error=False)
        if check_error:
            self.checkError()

        return result

    def checkError(self) -> Exception:
        """
        Check if an error occurred.

        Raises:
            self._ErrorFactory:
        Returns:
            Exception: See ErrorFactory
        """
        error_code, error_message = self.query('system:error?', check_error=False).split(',')
        if int(error_code) != 0:
            # logger.debug(f'{__name__}; error code: {error_code}')
            raise self._ErrorFactory(int(error_code), error_message)

    def idn() -> str:
        """returns the device identification information."""
        return self.query('*IDN?').strip('\n')

    def clrOutputProt(self) -> None:
        """If output protection was triggered for some reason, clear it."""
        self._write('output:protection:clear')

    def clrErrorQueue(self) -> None:
        """Clear all errors from the instrument error queue"""
        self._write('system:clear')

    def saveSetup(self, n) -> None:
        """Save current source configuration settings"""
        self._write(f'*SAV {n}')

    def recallSetup(self, n) -> None:
        """Recall a saved current source configuration"""
        self._write(f'*RCL {n}')

    def close(self) -> None:
        """Closes the socket connection"""
        self.sock.close()

    # context manager

    def __enter__(self):
        if not self.connected:
            self.connect()
        return self

    def __exit__(self, type, value, traceback):
        if self.connected:
            self.sock.close()
            return not self.connected
        else:
            return isinstance(value, TypeError)

    #-------------------------------------------------------#
    #------------------ Utility functions ------------------#
    #-------------------------------------------------------#

    def getMaxMinOutput(self):
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

    def getStatus(self):
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

    def setMaxCurrVolt(self,  currentLim=5, voltageLim=10, verbose=False):
        """
        Set maximum current values for each ECB channel, as long as they are under the threshold specified in the API source code.
        Args:
        -maxValue

        Returns: error code iff an error occurs
        """
        if currentLim > self.MAX_CURR:
            self.currentLim = self.MAX_CURR
            if verbose:
                print('Current cannot be higher than 5.05A')
        else:
            self.currentLim = currentLim
        if voltageLim > self.MAX_VOLT:
            self.voltageLim = self.MAX_VOLT
            if verbose:
                print('Voltage cannot be higher than 30V')
        else:
            self.voltageLim = voltageLim

        self._write('current:limit:state ON;:voltage:limit:state ON')
        self._write(f'current:limit {self.currentLim};:voltage:limit {self.voltageLim}')

    def setOutputSpeed(self, mode='normal', time=1):
        """
        Set the reaction speed of the output.

        Args:
            mode (str, optional): normal, fast or time. Defaults to 'normal'.
            time (float, optional): 0.001 - 86400s, only in time mode. Defaults to 1.
        """
        modes = ['normal', 'fast', 'time']
        basecmd = 'output:speed'

        if not mode in modes:
            return

        self._write(f'{basecmd} {mode}')
        if mode == 'time':
            self._write(f'{basecmd}:time {time}')

    def outputInfo(self):
        """
        Returns output type (high or low capacitance) and relay mode.
        """
        output_type = self.query('output:type?')
        output_mode = self.query('output:relay:mode?')
        output_speed = self.query('output:speed?')
        res = 'type: ' + output_type + '; mode: ' + output_mode + '; speed: ' + output_speed
        return res