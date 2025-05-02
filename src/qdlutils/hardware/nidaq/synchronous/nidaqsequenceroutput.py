import logging
import numpy as np
import nidaqmx
import nidaqmx.constants

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
            sample_rate: float = 1000000,
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
        sample_rate: float
            Default sample rate of the task. If using the clock task to manage the timing, this
            argument should be larger than the clock rate.
        '''
        self.clock_device = None
        self.task = None
        self.data = None

    def build(
            self,
            clock_device: str,
            sample_rate: float
    ) -> None:
        '''
        Instantiates the `nidaqmx.Task` corresponding to the output, sets the timing of the task
        (typically utilizing the clock signal), configures the start trigger to begin with the start
        of the clock task.

        Parameters
        ----------
        clock_device: str
            String indicating the device of the clock task generated in the `NidaqSequencer` method
            `NidaqSequencer.run_sequence()`.
        sample_rate: float
            Sample rate for the output task. This can be used to directly set the sample rate to a
            value other than the clock's sample rate but need not in all cases.
        '''
        pass

    def write(
            self,
            data: np.ndarray
    ):
        '''
        Writes the data to the task. Generically should validate the data first.

        Parameters
        ----------
        data: np.ndarray
            Data vector to write during the sequence.
        '''
        pass

    def set(
            self,
            setpoint: float | int | bool
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
            data: float | int | bool | np.ndarray
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
            n_samples: int,
            sample_rate: float = 1000000,
            min_voltage: float = -5,
            max_voltage: float = +5
    ) -> None:
        
        self.name = name
        self.device = device
        self.channel = channel
        self.n_samples = n_samples
        self.sample_rate = sample_rate
        self.min_voltage = min_voltage
        self.max_voltage = max_voltage

        self.clock_device = None
        self.task = None
        self.data = None
        
    def build(
            self,
            clock_device: str = 'Dev1',
            sample_rate: float = None
    ):
        
        # Update sample rate if needed
        if sample_rate is not None:
            self.sample_rate = sample_rate

        # Save clock device
        self.clock_device = clock_device

        # Create task
        self.task = nidaqmx.Task()

        # Create the AO voltage channel and configure the timing
        self.task.ao_channels.add_ao_voltage_chan(self.device+'/'+self.channel)

        # Configure the timing
        self.task.timing.cfg_samp_clk_timing(
            self.sample_rate,
            source='/'+self.clock_device+'/di/SampleClock',
            sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
            samps_per_chan=self.n_samples
        )
        # Configure the trigger for the AO task
        self.task.triggers.start_trigger.cfg_dig_edge_start_trig(
            '/'+self.clock_device+'/di/StartTrigger'
        )

    def write(
            self, 
            data: np.ndarray,
    ):
        # Check if the data has the right shape
        if len(data) != self.n_samples:
            raise ValueError('Length of data does not match specified number of samples.')
        # Validate that the data is in range
        self._validate_data(data)
        # Record the data vector
        self.data = data
        # Write the data to the task
        self.task.write(data)

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

    def _validate_values(
            self,
            data: float | int | np.ndarray,
    ):
        try:
            data = np.array(data)
        except:
            raise TypeError(f'Data {data} is not a valid type.')
        if np.any(data < self.min_voltage):
            raise ValueError(f'Data {data} contains points less than {self.min_voltage:.3f}.')
        if np.any(data > self.max_voltage):
            raise ValueError(f'Data {data} contains points greater than {self.max_voltage:.3f}.')

