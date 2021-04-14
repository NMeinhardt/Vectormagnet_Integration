
import socket
from time import sleep, time


class ITPowerSupplyDriver:
    """ITECH IT6432 bipolar DC power supply driver wrapper.

    """

    def __init__(self, channel: int, IP_address: str, port: int, 
                maxCurrent: float = 5.05, maxVoltage:float = 30):
        """Instance constructor.

        :param channel: channel number, use 1, 2 or 3
        :param IP_address: IP address of power supply
        :param port: port for communication with power supply
        :param maxCurrent: maximum allowed current
        :param maxVoltage: maximum allowed voltage
  
        """
        self._channel = channel
        self._connected = False

        self._sock = socket.socket()
        self._host = IP_address
        self._port = port
        self._timeout = 5.0

        self._read_termination = '\n'
        self._chunk_size = 1024

        self.MAX_CURR = maxCurrent
        self.MAX_VOLT = maxVoltage
        self.current_lim = 0
        self.voltage_lim = 0

    @staticmethod
    def _ErrorFactory(code, msg=''):
        """Generate Python errors based on IT6432 error codes.

        :param code: whether to check for errors explicitly, defaults to True.
        :type code: int
        :param msg: The error message, only included if the error code is unknown.
        :type msg: str, optional

        :returns: some subclass of Exception
            
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

    def connect(self):
        """Connects to the the device
        """
        try:
            self._sock.connect((self._host, self._port))
            self._connected = True
            self._sock.settimeout(self._timeout)

            limits = self.getMaxMinOutput()
            self.current_lim = limits[0]
            self.voltage_lim = limits[2]

        except Exception as exc:
            # logger.error(f'A problem occured while trying to connect to channel
            # {self._channel}: {exc}')
            print(f'A problem occured while trying to connect to channel {self._channel}: {exc}')

    @property
    def channel(self) -> int:
        """Return the channel of current source 

        """
        return self._channel

    @property
    def connected(self) -> int:
        """Return True if device is connected and False else

        """
        return self._connected

    def _write(self, cmd: str, check_error: bool = True):
        """Writes command as ascii characters to the instrument.
        If there is an error, it is saved to the log.

        :param cmd: an SCPI command
        :type cmd: str
        :param check_error: whether to check for errors explicitly, defaults to True.
        :type check_error: bool, optional
        
        :raise: BaseException: if check_error is true and an error occurred. 
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
        """Reads message sent from the instrument on the connection, one chunk (1024 bytes) at a time.

        :param chunk_size: expected chunk size to be received. Defaults to 0.
        :type chunk_size: int, optional
        :param check_error: whether to check for errors explicitly, defaults to True.
        :type check_error: bool, optional
        
        :raise: BaseException: if check_error is true and an error occurred. 

        :returns: the decoded (from ascii) received message
        :rtype: str

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
            print(f'{__name__} Timeout occurred! on {self._channel}')
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

    def _query(self, cmd: str, check_error: bool = True) -> str:
        """Query the current source with any command

        :param cmd: an SCPI command
        :type cmd: int
        :param check_error: whether to check for errors explicitly, defaults to True.
        :type check_error: bool, optional
        
        :raise: BaseException: if check_error is true and an error occurred. 

        :returns: the answer from the device
        :rtype: str

        """
        result = None
        self._write(cmd, check_error=False)
        sleep(0.1)
        result = self._read(check_error=False)
        if check_error:
            self.checkError()

        return result

    def checkError(self) -> None:
        """Check if an error occurred.

        :raise: self._ErrorFactory:

        :returns: Exception: See ErrorFactory
        :rtype: str

        """
        error_code, error_message = self._query('system:error?', check_error=False).split(',')
        if int(error_code) != 0 and int(error_code) != 224:
            # logger.debug(f'{__name__}; error code: {error_code}')
            raise self._ErrorFactory(int(error_code), error_message)

    def idn(self) -> str:
        """Returns the device identification information.
        """
        return self._query('*IDN?').strip('\n')

    def clrOutputProt(self):
        """If output protection was triggered for some reason, clear it.
        """
        self._write('output:protection:clear')

    def clrErrorQueue(self):
        """Clear all errors from the instrument error queue
        """
        self._write('system:clear')

    def saveSetup(self, n: int):
        """Save current source configuration settings

        :param n: 0-100
        :type n: int
        """
        self._write(f'*SAV {n}')

    def recallSetup(self, n: int):
        """Recall a saved current source configuration

        :param n: 0-100
        :type n: int
        """
        self._write(f'*RCL {n}')

    def close(self):
        """Closes the socket connection
        """
        self._sock.close()

    def getMaxMinOutput(self) -> tuple:
        """Get maximum/minimum current/voltage values for each current channel.

        :returns: maximum, minimum current, maximum, minimum voltage
        :rtype: float
        """
        max_curr = self._query('current:maxset?')
        max_volt = self._query('voltage:maxset?')
        min_curr = self._query('current:minset?')
        min_volt = self._query('voltage:minset?')

        return float(max_curr), float(min_curr), float(max_volt), float(min_volt)

    def getStatus(self) -> dict:
        """Get the current status of the device by sending a query
        for the different status registers. Used for low-level debugging.

        :returns: messages corresponding to any of the bits which were set.
        :rtype: dict
        """
        messages = {}

        status = int(self._query('*STB?'))
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

        status = int(self._query('*ESR?'))
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

        status = int(self._query('status:questionable:condition?'))
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

        status = int(self._query('status:operation:condition?'))
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

    def get_current(self, meas_type : str ='') -> float:
        """Perform current measurement and return estimated value

        :param meas_type: Measurement types {"", "min", "acdc", "max"}, which are either
            a DC measurement, an RMS value or minimum/maximum.
        """
        # query current measurement
        if meas_type != "":
            res = self._query(f'measure:current:{meas_type}?')
        else:
            res = self._query('measure:current?')

        # if a list is returned, take first entry
        if isinstance(res, list):
            res = res[0]

        return float(res)

    def get_voltage(self, meas_type : str ='') -> float:
        """Perform voltage measurement and return estimated value

        :param meas_type: Measurement types {"", "min", "acdc", "max"}, which are either
            a DC measurement, an RMS value or minimum/maximum.
        """
        # query current measurement
        if meas_type != "":
            res = self._query(f'measure:voltage:{meas_type}?')
        else:
            res = self._query('measure:voltage?')

        # if a list is returned, take first entry
        if isinstance(res, list):
            res = res[0]

        return float(res)

    def get_power(self, meas_type : str ='') -> float:
        """Perform power measurement and return estimated value

        :param meas_type: Measurement types {"", "min", "acdc", "max"}, which are either
            a DC measurement, an RMS value or minimum/maximum.
        """
        # query current measurement
        if meas_type != "":
            res = self._query(f'measure:power:{meas_type}?')
        else:
            res = self._query('measure:power?')

        # if a list is returned, take first entry
        if isinstance(res, list):
            res = res[0]

        return float(res)


    def outputInfo(self) -> str:
        """Return output type (high or low capacitance), relay mode (high impedance) and output speed as str. 
        """
        output_type = self._query('output:type?')
        output_mode = self._query('output:relay:mode?')
        output_speed = self._query('output:speed?')
        res = 'type: ' + output_type + '; mode: ' + output_mode + '; speed: ' + output_speed

        return res

    def set_maximum_current(self, current_lim: float = 5, verbose: bool = False):
        """Set maximum current values for each ECB channel, as long as they are under the threshold specified in the API source code.

        :param current_lim: desired maximum current. Defaults to 5.
        :type current_lim: float, optional
        :param verbose: print debug messages. Defaults to False.
        :type verbose: bool, optional
        """
        if current_lim > self.MAX_CURR:
            self.current_lim = self.MAX_CURR
            if verbose:
                print('Current limit cannot be higher than 5.05A')
                # logger.debug('Current limit cannot be higher than 5.05A')
        else:
            self.current_lim = current_lim

        self._write('current:limit:state ON')
        self._write(f'current:limit {self.current_lim}')

    def set_maximum_voltage(self, voltage_lim: float = 10, verbose: bool = False):
        """Set maximum voltage values for each ECB channel, as long as they are under the threshold specified in the API source code.

        :param voltage_lim: desired maximum voltage. Defaults to 10.
        :type voltage_lim: float, optional
        :param verbose: print debug messages. Defaults to False.
        :type verbose: bool, optional
        """
        if voltage_lim > self.MAX_VOLT:
            self.voltage_lim = self.MAX_VOLT
            if verbose:
                print('Voltage cannot be higher than 30V')
                # logger.debug('Voltage limit cannot be higher than 30V')
        else:
            self.voltage_lim = voltage_lim

        self._write('voltage:limit:state ON')
        self._write(f'voltage:limit {self.voltage_lim}')

    def set_output_speed(self, mode: str = 'normal', time: float = 1):
        """Set the reaction speed of the output.

        :param mode: 'normal', 'fast' or 'time'. Defaults to 'normal'.
        :type mode: str, optional
        :param time: 0.001 - 86400s, only in time mode. Defaults to 1.
        :type time: float, optional

        """
        modes = ['normal', 'fast', 'time']
        basecmd = 'output:speed'

        if mode not in modes:
            return

        self._write(f'{basecmd} {mode}')
        if mode == 'time':
            self._write(f'{basecmd}:time {time}')

    def set_operation_mode(self, mode: str):
        """Switch between local and remote operation mode.

        :param mode: can be 'local' or 'remote'
        :type mode: str
        """
        if mode == 'local':
            self._write("system:local")
        elif mode == 'remote':
            self._write("system:remote")

    def set_current(self, value:float):
        """Set current to provided target value

        :param value: new target current [A] of current supply
        :type value: float
        """
        if value <= self.current_lim:
            self._write(f'current {value:.3f}A')
        else:
            self._write(f'current {self.current_lim:.3f}A')

    def set_voltage(self, value:float):
        """Set voltage to provided target value

        :param value: new target voltage [V] of current supply
        :type value: float
        """
        if value <= self.voltage_lim:
            self._write(f'voltage {value:.3f}V')
        else:
            self._write(f'voltage {self.voltage_lim:.3f}V')

    def enable_output(self):
        """Enable output of power supply
        """
        self._write("output 1")

    def disable_output(self):
        """Enable output of power supply
        """
        self._write("output 0")

    def get_output_state(self) -> str:
        """Return output state of power supply, which can be 'on' or 'off.
        """
        if self._query("output?") == "1":
            return 'on'
        else:
            return 'off'
    
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