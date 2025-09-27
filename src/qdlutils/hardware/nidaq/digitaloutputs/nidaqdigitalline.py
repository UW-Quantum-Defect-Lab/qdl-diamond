import logging
import nidaqmx
import time


class NidaqDigitalLineController:
    '''
    This class is a base class for controlling individual digital output lines on the DAQ. Note that
    the general use case for this class is to simply write single values to individual digital
    output lines. If you wish to have timed pulse sequences or similar processes you should consider
    using the `NidaqSequencer` classes.

    Attributes
    ----------
    logger : logging.Logger
        A logging.Logger instantiation for writing log results to the terminal.
    device_name : Str
        Name of the NIDAQ device name to communicate with.
    write_channel : Str
        Which channel of the NIDAQ device to write instructions to.
    read_channel : Str
        Which NIDAQ analog input channel to read input from.
    min_voltage : Float
        Minimum allowed voltage for the specific instantiation of the controller.
        Note that this is distinct from the hardware-limited minimum voltage (which
        is a property of the DAQ itself) and this value should be kept within such
        limits during operation.
    max_voltage : Float
        Maximum allowed voltage for the specific instantiation of the controller.
        Note that this is distinct from the hardware-limited maximum voltage (which
        is a property of the DAQ itself) and this value should be kept within such
        limits during operation.
    settling_time_in_seconds : Float
        Determines how many seconds the DAQ pauses after each write command to
        allow for the hardware being controlled to settle.
    last_write_value : Float
        Internal value which tracks the last value written to the DAQ channel.
        On initialization it is set to None.

    Methods
    -------
    configure(config_dict) -> None
        Loads settings for the controller based off of entries in config_dict with matching
        keys to attributes. If a key is missing the number is not changed.
    get_current_voltage() -> Float
        Returns the current voltage 
    go_to_voltage(voltage) -> None
        Sets the output voltage to the specfied voltage value.
    validate_value(voltage) -> Bool
        Validates if parameter voltage is within the range specified by min/max voltage.

    Notes
    -----
    This base class can either be copied and modified or inherited from in order to create
    NIDAQ analog output controllers for other hardware.
    To implement an inherited class, create private methods to convert between the external
    unit (e.g. position, wavelength) and the internal unit (voltage) and vice versa.
    Then in the __init__() call of your child class, call super().__init__(*args) to set
    the voltage parameters. You can then make wrapper functions which call the 
    NidaqVoltageController.get_current_voltage() and .go_to_voltage() methods passing or
    returning values converted to and from the external quantity respectively.
    Also you will need to overwrite the self.configure() method to update the specific
    parameters for the child class.
    '''

    def __init__(self, 
                 device: str = 'Dev1',
                 port: str = 'port0',
                 line: str = 'line0') -> None:

        self.logger = logging.getLogger(__name__)
        self.device = device
        self.port = port
        self.line = line
        self.last_write_value = None

    def configure(self, config_dict: dict) -> None:
        '''
        This method configures the controller based off of matching keys in
        config_dict. If a key is not present the value remains unchanged.

        Parameters
        ----------
        config_dict : dict
            A dictionary whose keys can contain the attributes of this class.
            If a key matches the corresponding attribute is updated to the
            corresponding value in config_dict.

        Returns
        -------
        None
        '''
        self.device = config_dict.get('device', self.device)
        self.port = config_dict.get('port', self.port)
        self.line = config_dict.get('line', self.line)

    def get_current_voltage(self) -> float:
        '''
        Returns the current output value.

        Parameters
        ----------
        None

        Returns
        -------
        val : bool
            The current value (true or false).
        '''
        return self.last_write_value

    def set_value(self, val: bool) -> None:
        '''
        Sets the voltage on the DAQ channel.

        Parameters
        ----------
        val : bool
            The value to write to the line.

        Returns
        -------
        None
        '''
        with nidaqmx.Task() as task:
                task.do_channels.add_do_chan(self.device + '/' + self.port + '/' + self.line)
                task.write(val)
        self.last_write_value = val
        self.logger.debug(f'Set {self.device}/{self.port}/{self.line} to {self.last_write_value}')

    def toggle(self) -> None:
         '''
         Toggles the current output.
         '''
         self.set_value(val = not self.last_write_value)
