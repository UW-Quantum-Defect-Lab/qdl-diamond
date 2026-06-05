import serial
import time
import logging

from qdlutils.hardware.wavemeters.wavemeters import WavemeterController

class BurleighWA1600(WavemeterController):

    '''
    Class for interfacing with the Burleigh WA-1600 wavemeter via RS-232 serial connection.
    '''

    def __init__(
            self,
            port: str='COM1',
            timeout: float=2,
            units: str='FREQ',
            mode: str='READ'
    ):
        '''
        Parameters
        ----------
        port : str
            A string for the communication port on which to open the serial channel.
        timeout : float
            Length of time in seconds to wait for a readout
        units : str
            String indicating what type of data to read out. Options are 'WAV' = wavelength in air 
            in nm, 'WNUM' = wavenumber in 1/cm, 'FREQ' = frequency in GHz.
        mode : str
            String indicating the acquisition mode. Options are 'READ' = read which waits for the 
            next scan to complete and outputs the value, 'FETC' = fetch which returns the last 
            read value (if queried too quickly can return a repeat measurement value).
        '''
        self.port = port
        self.timeout = timeout
        self.units = units
        self.mode = mode
        self.channel_open = False
        # Serial port object
        self.ser = None
        # Time reference
        self.start_time = None

        # Form the readout command
        self.read_cmd = (':'+mode+':'+units+'?\n').encode('utf-8')

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
        # Flag channel as open
        self.channel_open = True
        # Get the start time
        self.start_time = int(time.time() * 100) # In units of 10 ms

    def close(self):
        '''
        Closes the serial connection.
        '''
        self.ser.close()
        self.channel_open = False

    def readout(self):
        '''
        Gets the current reading from the wavemeter.

        Note that if the sweep is happening quickly over a large bandwidth the wavemeter may not
        be able to keep up. When this happens a value of 0 is returned and should be handled
        properly.

        Returns
        -------
        timestamp : int
            The internal clock time stamp in units of 10 ms
        reading : float
            The current output value in the current units set on the tool. May not match the units
            in the software if the user has manually changed it after initialization.
        '''
        # Write the query command to the channel
        self.ser.write(self.read_cmd)
        # Read the next line, remove the newline
        if self.ser.readline().strip() == b'':
            data = 0
        else:
            data = float(self.ser.readline().strip())
        
        # Get the current time
        current_time = int(time.time() * 100) # In units of 10 ms
        # Return the data with timetag referenced to the channel opening
        return (current_time - self.start_time), data
    
    def read_current_val(self):
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
        self.ser.write(self.read_cmd)
        # Read the next line, remove the newline
        data = self.ser.readline().strip()
        return float(data)