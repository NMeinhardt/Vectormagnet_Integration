import socket
from time import sleep, time
from threading import RLock
import enum



@enum.unique
class OutputState(enum.Enum):
    """Magnet power states.
    
    """
    ON = 1
    OFF = 2

class ITPowerSupplyDriver(object):
    """ITECH IT6432 bipolar DC power supply driver wrapper.
    
    """

    def __init__(self, channel: int, IP_address: str, port: int, 
                maxCurrent: float = 5.05, maxVoltage:float = 30):
        """Instance constructor.

        :param channel: channel number, use 1, 2 or 3
        :param IP_address: IP address of power supply
        :param port: port for communication with power supply
        :param maxCurrent: maximum allowed current as a soft limit
        :param maxVoltage: maximum allowed voltage as a soft limit
  
        """
        self._channel = channel
        self._connected = False

        # connection settings
        self._sock = socket.socket()
        self._host = IP_address
        self._port = port
        self._timeout = 10.0
        self._read_termination = '\n'
        self._chunk_size = 1024

        # hardware limits for current and voltage, get updated once connecting to hardware
        self.MAX_CURR = 0
        self.MAX_VOLT = 0

        # soft limits for current and voltage
        self.current_lim = maxCurrent
        self.voltage_lim = maxVoltage

        # locks to prevent multiple threads from sending/receiving data simultaneously via socket
        self.lock_sending = RLock()
        self.lock_receiving = RLock()
            

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


    def connect(self):
        """Connect to the device

        """
        logger.debug(f'DRV :: IT6432 :: connect :: CH {self._channel}')
        print(f'DRV :: IT6432 :: connect :: CH {self._channel}')
        try:
            self._sock.connect((self._host, self._port))

        except Exception as err:
            logger.error(err)

        else:
            self._connected = True
            self._sock.settimeout(self._timeout)

            limits = self.getMaxMinOutput()
            self.MAX_CURR = limits[0]
            self.MAX_VOLT = limits[2]


    def close(self):
        """Closes the socket connection
        """
        logger.debug(f'DRV :: IT6432 :: close :: CH {self._channel}')
        self._sock.close()


    def _send(self, cmd: str, check_error: bool = True):
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
            with self.lock_sending:
                # print(f'(ch {self._channel}): >> {cmd[:-1]}')
                self._sock.sendall(cmd.encode('ascii'))
        except (ConnectionResetError, ConnectionError, ConnectionRefusedError, ConnectionAbortedError) as err:
            print(f'error on (ch {self._channel}) in _send: cmd= {cmd[:-1]}')
            logger.error(err)

        if check_error:
            self.checkError()


    def _recv(self, chunk_size: int = 1024, check_error: bool = True) -> str:
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

        try:
            while True:
                to_read_len = chunk_size - read_len
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
            logger.debug(f'{__name__} Timeout occurred on CH {self._channel}')
            return ''

        try:
            res = chunk.decode('ascii').strip('\n')
        except UnicodeDecodeError:
            res = chunk.decode('uft8').strip('\n')
            logger.error(f'{__name__} Non-ascii string received on CH {self._channel}: {res}')

        # print(f'(ch {self._channel}): << {res}')

        if check_error:
            self.checkError()

        return res


    def _send_and_recv(self, cmd: str, check_error: bool = True) -> str:
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
        with self.lock_receiving:
            self._send(cmd, check_error=False)
            result = self._recv(check_error=False)
            
        if check_error:
            self.checkError()

        return result


    def clrOutputProt(self):
        """Clear output protection of current supply.
        """
        logger.debug(f'DRV :: IT6432 :: clrOutputProt on CH {self._channel}')
        self._send('output:protection:clear')


    def clrErrorQueue(self):
        """Clear all errors from the instrument error queue
        """
        logger.debug(f'DRV :: IT6432 :: clrErrorQueue on CH {self._channel}')
        self._send('system:clear', check_error=False)


    def set_operation_mode(self, mode: str):
        """Switch between local and remote operation mode.

        :param mode: can be 'local' or 'remote'
        :type mode: str
        """
        if mode == 'local':
            self._send("system:local")
        elif mode == 'remote':
            self._send("system:remote")


    def set_current(self, value:float):
        """Set current to provided target value

        :param value: new target current [A] of current supply
        :type value: float
        :raises ExceedsLimits: When provided value exceeds software defined limit.
        """
        if value > self.current_lim:
            raise ExceedsLimits

        self._send(f'current {value:.3f}A')


    def set_voltage(self, value:float):
        """Set voltage to provided target value

        :param value: new target voltage [V] of current supply
        :type value: float
        :raises ExceedsLimits: When provided value exceeds software defined limit.
        """
        if value > self.voltage_lim:
            raise ExceedsLimits

        self._send(f'voltage {value:.3f}V')


    def get_current(self, meas_type : str ='') -> float:
        """Perform current measurement and return estimated value

        :param meas_type: Measurement types {"", "min", "acdc", "max"}, which are either
            a DC measurement, an RMS value or minimum/maximum.
        """
        # query current measurement
        if meas_type != "":
            res = self._send_and_recv(f'measure:current:{meas_type}?')
        else:
            res = self._send_and_recv('measure:current?')

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
            res = self._send_and_recv(f'measure:voltage:{meas_type}?')
        else:
            res = self._send_and_recv('measure:voltage?')

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
            res = self._send_and_recv(f'measure:power:{meas_type}?')
        else:
            res = self._send_and_recv('measure:power?')

        # if a list is returned, take first entry
        if isinstance(res, list):
            res = res[0]

        return float(res)


    def enable_output(self):
        """Enable output of power supply
        """
        self._send("output 1")


    def disable_output(self):
        """Enable output of power supply
        """
        self._send("output 0")

    
    def get_output_state(self) -> OutputState:
        """Return output state of power supply, which can be 'on' or 'off.
        """
        if self._send_and_recv("output?") == "1":
            return OutputState.ON
        else:
            return OutputState.OFF


    def getMaxMinOutput(self) -> tuple:
        """Get maximum/minimum current/voltage values for each current channel.

        :returns: maximum, minimum current, maximum, minimum voltage
        :rtype: float
        """
        MAX_CURR = self._send_and_recv('current:maxset?', check_error=False)
        MIN_CURR = self._send_and_recv('current:minset?', check_error=False)
        MAX_VOLT = self._send_and_recv('voltage:maxset?', check_error=False)
        MIN_VOLT = self._send_and_recv('voltage:minset?', check_error=False)

        return float(MAX_CURR), float(MIN_CURR), float(MAX_VOLT), float(MIN_VOLT)


    def set_maximum_current(self, current_lim: float = 5):
        """Set soft maximum limit on current values, as long as it respects the hard limit set by the hardware.

        :param current_lim: desired maximum current. Defaults to 5.
        :type current_lim: float, optional
        :raises ValueError: negative numbers are not permitted.
        """
        if current_lim < 0:
            raise ValueError

        if current_lim > self.MAX_CURR:
            self.current_lim = self.MAX_CURR
            logger.debug(f'DRV :: IT6432 :: set_maximum_current :: Current limit cannot be higher than {self.MAX_CURR} A')
        else:
            self.current_lim = current_lim

        self._send('current:limit:state ON')
        self._send(f'current:limit {self.current_lim}')


    def set_maximum_voltage(self, voltage_lim: float):
        """Set soft maximum limit on voltage values, as long as it respects the hard limit set by the hardware.

        :param voltage_lim: desired maximum voltage, must be a nonzero number
        :type voltage_lim: float
        :raises ValueError: negative numbers are not permitted.
        """
        if voltage_lim < 0:
            raise ValueError

        if voltage_lim > self.MAX_VOLT:
            self.voltage_lim = self.MAX_VOLT
            logger.debug(f'DRV :: IT6432 :: set_maximum_voltage :: Voltage limit cannot be higher than {self.MAX_VOLT} V')
        else:
            self.voltage_lim = voltage_lim

        self._send('voltage:limit:state ON')
        self._send(f'voltage:limit {self.voltage_lim}')

    
    def set_hardware_limits(self, maxCurrent : float, maxVoltage : float):
        """Reset the hardware limit on voltage and current.
        """
        self.MAX_CURR = maxCurrent
        self.MAX_VOLT = maxVoltage


    def set_new_address(self, IP_address : str, port: int):
        """Reset the hardware limit on voltage.
        """
        self._host = IP_address
        self._port = port


    def checkError(self) -> None:
        """Check if an error occurred.

        :raise: self._ErrorFactory:

        :returns: Exception: See ErrorFactory
        :rtype: str

        """
        response = self._send_and_recv('system:error?', check_error=False).split(',')
        if response == ['']:
            return
        try:
            error_code, error_message = response
        except ValueError:
            try:
                error_code = int(response)
            except ValueError:
                logger.error(f'DRV :: IT6432 :: checkError :: channel = {self._channel}, response = {response}')
            except Exception as e:
                logger.error(f'DRV :: IT6432 :: checkError :: channel = {self._channel}, response = {response} - {type(e)}: {e}')
            else:
                if int(error_code) != 0 and int(error_code) != 224:
                    raise self._ErrorFactory(int(error_code), f'(ch {self._channel}): no message provided')
        else:
            if int(error_code) != 0 and int(error_code) != 224:
                raise self._ErrorFactory(int(error_code), error_message)
            


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

class ExceedsLimits(Exception):
    """Raised when a value that is larger than a given limit should be set.
    """
    pass
        

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
        logger.error(f'{code}: {msg}')
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