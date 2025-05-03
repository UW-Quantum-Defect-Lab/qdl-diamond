import logging
import numpy as np
import nidaqmx
import nidaqmx.constants

# Because we are on Python 3.9 type union operator `|` is not yet implemented
from typing import Union

'''
This file contains the `NidaqSequencerOutput` base class and its child classes which represent
individual signals or hardware components that should be outputted by the DAQ during a sequence as
managed by the `NidaqSequencer` class. For more details on the structure of the `NidaqSequencer` 
class and general information about sequencing with the DAQ board please see `nidaqsequencer.py`.

The base class `NidaqSequencerOutput` provides the template for general output through any type of
channel or terminal on the physical DAQ board. This class effectively represents the connection on
the DAQ through which data is written. As such, it serves as a constructor and manager of a general
output-oriented `nidaqmx.Task` such as analog output or digital output.

The `NidaqSequencerOutput` class when initialized simply stores the necessary information to
construct the task (e.g. the DAQ device, channel, etc.), and provides attributes to store the data
to write.

One then can run the `NidaqSequencerOutput.build()` method to create the actual `nidaqmx.Task`, and
then use the `NidaqSequencerOuput.write()` method to write data to the channel. The creation of the
task, and subsequent writing of data, are created to start when the `NidaqSequencer` clock begins,
thus correlating any included I/O streams.

One child class should be created for each type of output signal channel, e.g. analog voltage output
or digital voltage output, etc.
'''

class NidaqSequencerOutput:

    '''
    Base class for `NidaqSequencer` output signal control.
    '''

    def __init__(
            self,
            name: str,
            device: str,
            channel: str,
            **kwargs
    ) -> None:
        '''
        Parameters
        ----------
        name: str
            Name of the output used for referencing.
        device: str
            Name of the DAQ device to write data to
        channel: str
            Name of the DAQ channel to write data to
        '''
        self.name = name
        self.device = device
        self.channel = channel

        self.task = None
        self.data = None
        self.clock_device = None
        self.sample_rate = None
        self.n_samples = None

    def build(
            self,
            data: np.ndarray,
            clock_device: str,
            sample_rate: float
    ) -> None:
        '''
        Instantiates the `nidaqmx.Task` corresponding to the output, sets the timing of the task
        (typically utilizing the clock signal), configures the start trigger to begin with the start
        of the clock task. Then writes the data.

        Parameters
        ----------
        data : np.ndarray
            Data array to write during the sequence.
        clock_device: str
            String indicating the device of the clock task generated in the `NidaqSequencer` method
            `NidaqSequencer.run_sequence()`.
        sample_rate: float
            Sample rate for the output task. This can be used to directly set the sample rate to a
            value other than the clock's sample rate but need not in all cases.
        '''
        pass

    def set(
            self,
            setpoint: Union[float, int, bool]
    ) -> None:
        '''
        A utility method for setting the value of the output channel to the `setpoint` outside of 
        the sequence. This can be done for initialization.

        Parameters
        ----------
        setpoint: float | int | bool
            Value to set the output channel to.
        '''
        pass

    def close(
            self
    ) -> None:
        '''
        Stops the task and closes it, freeing up resources on the DAQ.
        '''
        self.task.stop()
        self.task.close()

    def _validate_data(
            self,
            data: Union[float, int, bool, np.ndarray]
    ) -> None:
        '''
        Checks if the provided `data` is valid. Can be used to protect hardware from incorrect
        set values in the software. The definition of "valid" depends on the type of channel.

        Parameters
        ----------
        data: float | int | bool | np.ndarray
            Some data to validate.
        '''
        pass



class NidaqSequencerAOVoltage(NidaqSequencerOutput):

    def __init__(
            self,
            name: str,
            device: str,
            channel: str,
            min_voltage: float = -5,
            max_voltage: float = 5
    ) -> None:
        
        self.name = name
        self.device = device
        self.channel = channel
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage

        self.task = None
        self.data = None
        self.clock_device = None
        self.sample_rate = None
        self.n_samples = None
        
    def build(
            self,
            data: np.ndarray,
            clock_device: str,
            sample_rate: float,
    ):
        # Validate the data
        self._validate_data(data)

        # Save parameters
        self.data = data
        self.clock_device = clock_device
        self.sample_rate = sample_rate
        self.n_samples = len(data)

        # Create the task
        self.task = nidaqmx.Task()
        # Create the AO voltage channel
        self.task.ao_channels.add_ao_voltage_chan(self.device+'/'+self.channel)
        # Configure the timing
        self.task.timing.cfg_samp_clk_timing(
            sample_rate,
            source='/'+self.clock_device+'/di/SampleClock',
            sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
            samps_per_chan=self.n_samples
        )
        # Configure the trigger for the AO task
        self.task.triggers.start_trigger.cfg_dig_edge_start_trig(
            '/'+self.clock_device+'/di/StartTrigger'
        )
        # Write the data to the task
        self.task.write(data)
        # Commit the task to the hardware
        self.task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)
        
    def set(
            self,
            setpoint: float
    ) -> None:
        # Verifty the setpoint is in range
        self._validate_data(setpoint)
        # Create a task on the voltage output, write the desired voltage
        with nidaqmx.Task() as task:
            task.ao_channels.add_ao_voltage_chan(self.device+'/'+self.channel)
            task.write(setpoint)

    def _validate_data(
            self,
            data: Union[float, int, np.ndarray],
    ):
        try:
            data = np.array(data)
        except:
            raise TypeError(f'Data type {type(data).__name__} is not a valid type.')
        
        if np.any(data < self.min_voltage):
            raise ValueError(f'Data contains points less than allowed minimum {self.min_voltage:.3f}.')
        if np.any(data > self.max_voltage):
            raise ValueError(f'Data contains points greater than allowed maximum {self.max_voltage:.3f}.')

