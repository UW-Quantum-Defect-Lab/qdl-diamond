import serial
import time
import logging

import qdlutils.hardware.wavemeters.wlmData as wlmData
import qdlutils.hardware.wavemeters.wlmConst as wlmConst

from qdlutils.hardware.wavemeters.wavemeters import WavemeterController

class WS7(WavemeterController):

    '''
    Class for interfacing with the WS7 High Finesse wavemeter using their provided API.

    NOTE: In order for this class to work you must open the wavemeter via the provided GUI
    application and then start data collection. If you stop it, then the return values appear to
    just be the last read value.
    '''

    def __init__(
            self,
            timeout: float=2,
            units: str='FREQ',
            mode: str='READ'
    ):
        '''
        Parameters
        ----------
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
        self.timeout = timeout
        self.units = units
        self.mode = mode
        self.channel_open = False

        # Load the library
        # I honestly have no idea what is going on here but it seems to work... Taken from
        # the 35share/Python/vasilis/codes_for_experiments on Dropbox.
        wlmData.LoadDLL('wlmData.dll')
        self.lib = wlmData.dll

        # Get the return type:
        if units == 'WAV':
            self.unit_id = wlmConst.cReturnWavelengthAir
        elif units == 'WNUM':
            self.unit_id = wlmConst.cReturnWavenumber
        elif units == 'FREQ':
            self.unit_id = wlmConst.cReturnFrequency
        else:
            self.unit_id = wlmConst.cReturnWavelengthVac

        # Time reference
        self.start_time = None

    def open(self):
        '''
        Opens a serial connection on the specified port to talk with the wavemeter
        '''
        # Flag channel as open
        self.channel_open = True
        # Get the start time
        self.start_time = int(time.time() * 100) # In units of 10 ms

    def close(self):
        '''
        Closes the serial connection.
        '''
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
        # Read the raw data, can be an error if the output is < 0
        raw = self.lib.GetWavelength(0.0)
        if raw < 0:
            data = 0
        else:
            # Convert from default value to target unit
            data = self.lib.ConvertUnit(raw, wlmConst.cReturnWavelengthVac, self.unit_id)
            data = float( data ) * 1000
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
        # Read the raw data, can be an error if the output is < 0
        raw = self.lib.GetWavelength(0.0)
        if raw < 0:
            data = 0
        else:
            # Convert from default value to target unit
            data = self.lib.ConvertUnit(raw, wlmConst.cReturnWavelengthVac, self.unit_id)
            data = float( data ) * 1000
        return data