import serial
import time
import logging

from qdlutils.hardware.wavemeters.wavemeters import WavemeterController

class CoherentWaveMaster(WavemeterController):

    '''
    Class for interfacing with the Coherent WaveMaster wavemeter via RS-232 serial connection.
    '''

    def __init__(
            self,
            port: str='COM1',
            timeout: float=2,
            units: str='F',
            mode: str='C',
            autocal: bool=False
    ):
        '''
        Parameters
        ----------
        port : str
            A string for the communication port on which to open the serial channel.
        timeout : float
            Length of time in seconds to wait for a readout
        units : str
            Single character for the units to read out. Options are 'A' = wavelength in air in nm,
            'V' = wavelength in vacuum in nm, 'F' = frequency in GHz, 'W' = wavenumber in 1/cm.
        mode : str
            Single character for the acquisition mode. Options are 'C' = CW, 'A' = CW average, and
            'P' = pulsed.
        autocal : bool
            Whether or not to have autocalibration active. Note that periodic autocalibration causes
            the scanner to not return data during the calibration sequence. This can cause gaps in
            the data so it is generally preferred to turn it off.
        '''
        self.port = port
        self.timeout = timeout
        self.units = units
        self.mode = mode
        self.autocal = autocal
        self.channel_open = False
        # Serial port object
        self.ser = None

    def open(self):
        '''
        Opens a serial connection on the specified port to talk with the wavemeter
        '''
        self.ser = serial.Serial(
            port=self.port,
            baudrate=9600,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            xonxoff=True,
            timeout=self.timeout,
        )

        # Configure the system units
        self.ser.write(('UNI '+self.units+'\r\n').encode('utf-8'))
        # Configure the system mode
        self.ser.write(('MDE '+self.mode+'\r\n').encode('utf-8'))
        # Configure the autocalibration setting
        if self.autocal is False:
            self.ser.write(('CAL OFF\r\n').encode('utf-8'))
        else:
            self.ser.write(('CAL ON\r\n').encode('utf-8'))
        # Flag channel as open
        self.channel_open = True

    def close(self):
        '''
        Closes the serial connection.
        '''
        self.ser.close()
        self.channel_open = False

    def readout(self):
        '''
        Gets the current reading from the wavemeter.

        Returns
        -------
        timestamp : int
            The internal clock time stamp in units of 10 ms
        reading : float
            The current output value in the current units set on the tool. May not match the units
            in the software if the user has manually changed it after initialization.
        '''
        # Write the query command to the channel
        self.ser.write('VAL?\n'.encode('utf-8'))
        # Read the output from the channel
        # The direct output value `data` is a byte string like b'VAL$ 351541,406828.8\r\n'.
        # First we ignore the first four characters, then split the rest at the comma.
        # The first item is the time stamp in units of 10 ms, the second item is the measurement
        # value in the current units (possibly different if modified after initialization).
        data = self.ser.readline()[4:].split(b',')
        # Note that if no reading is available then this script will error out here.
        return int(data[0]), float(data[1])
    
    def force_calibrate(self):
        '''
        Forces the autocalbration sequence by first turning off the autocalibration then turning it
        back on. Finally the autocalibration state is returned to the current controller setting.
        
        Note that the calibration sequence takes several seconds so this command should not be run 
        immediately prior to any time-sensitive data aquisition steps. Allow ample time for the 
        calibration sequence to finish before reading out data.
        '''
        # Turn the autocalibration off
        self.ser.write(('CAL OFF\r\n').encode('utf-8'))
        # Turn it back on. This initiates the calibration sequence
        self.ser.write(('CAL ON\r\n').encode('utf-8'))
        # Turn it back off if specified
        if self.autocal is False:
            self.ser.write(('CAL OFF\r\n').encode('utf-8'))
