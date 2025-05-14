import logging
import numpy as np

import nidaqmx
import nidaqmx.constants
import nidaqmx.errors
import nidaqmx.stream_writers

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

class NidaqSequencerOutputGroup:

    '''
    Base class for `NidaqSequencer` output signal control.
    '''

    def __init__(
            self,
            device_channels_dict: dict[str, tuple[str,str]],
            **kwargs
    ) -> None:
        '''
        Parameters
        ----------
        device_channels_dict: dict[str, tuple[str,str]]
            A dictionary describing the name and corresponding DAQ device channels to write output
            to. The keys are user-facing names of the output sources and the values are the
            corresponding channel in the form of a tuple `(device, channel)` e.g. `('Dev1','ao0')`.

            In implementations involving digital output, the "channel" can either be reinterpreted
            as either `(device, port)` (e.g. `('Dev1','port0')`) for port-based writing or as
            `(device, port/line)` (e.g. `('Dev1','port0/line0')) for line-based writing.

            Note that the usage of dictionaries in this case necessitates that the order of the keys
            is preserved (which is guaranteed in Python 3.7 and up). As a result, developers should
            refrain from directly modifying the `device_channels_dict` attribute after 
            instantiation.

            Finally, note that multi-device tasks are valid and should be accepted, however the
            prerequisite hardware and NI MAX configuration is required and not managed here.
        **kwargs:
            Any number of keyword arguments required for specific output implementations.
        '''
        self.device_channels_dict = device_channels_dict
        self.n_channels = len(device_channels_dict)
        self.source_names = [name for name in device_channels_dict]

        # Attributes to be utilized later
        self.task = None
        self.writer = None
        self.data = None
        self.clock_device = None
        self.sample_rate = None
        self.n_samples = None

    def build(
            self,
            data: dict[str, np.ndarray],
            clock_device: str,
            clock_terminal: str,
            sample_rate: float
    ) -> None:
        '''
        Instantiates the `nidaqmx.Task` corresponding to the output, sets the timing of the task
        (typically utilizing the clock signal), configures the start trigger to begin with the start
        of the clock task. Then writes the data.

        Parameters
        ----------
        data : dict[str, np.ndarray],
            Data array to write during the sequence.
        clock_device: str
            String indicating the device of the clock task generated in the `NidaqSequencer` method
            `NidaqSequencer.run_sequence()`.
        clock_terminal: str
            The terminal for the sequencer clock output to time the source task.
        sample_rate: float
            The sample rate of the outputs. Since the timing source is given by the clock signal,
            this parameter does not directly modify the actual sample rate.
        '''
        try:
            # Make the task, add the channels, configure timing, write data
            raise NotImplementedError('Subclasses must implement this method.')
        # Try to catch errors relating to multi-device approaches
        except (nidaqmx.errors.DaqResourceWarning, nidaqmx.errors.DaqWriteError) as e:
            raise RuntimeError(f'A DAQ error occured possibly relating to multi-device setup: {e}')
        # Raise any other errors
        except Exception as e:
            raise e

    def set(
            self,
            output_name: str,
            setpoint: Union[float, int, bool]
    ) -> None:
        '''
        A utility method for setting the value of the output channel to the `setpoint` outside of 
        the sequence. This can be done for initialization.

        Parameters
        ----------
        output_name: str
            The name of the output channel to set.
        setpoint: float | int | bool
            Value to set the output channel to.
        '''
        raise NotImplementedError('Subclasses must implement this method.')

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
            output_name: str,
            data: Union[float, int, bool, np.ndarray]
    ) -> None:
        '''
        Checks if the provided `data` is valid output for the specified output channel. Can be used
        to protect hardware from incorrect set values in the software. The definition of "valid" 
        depends on the type of channel.

        Parameters
        ----------
        output_name: str
            Name of the output channel to verify data against.
        data: float | int | bool | np.ndarray
            Some data to validate.
        '''
        raise NotImplementedError('Subclasses must implement this method.')



class NidaqSequencerAOVoltageGroup(NidaqSequencerOutputGroup):

    '''
    This class represents the controller for `NidaqSequencer` analog output voltage control.
    '''

    def __init__(
            self,
            device_channels_dict: dict[str, tuple[str,str]],
            device_limits_dict: dict[str, tuple[float, float]]
    ) -> None:
        '''
        Parameters
        ----------
        device_channels_dict: dict[str, tuple[str,str]]
            A dictionary describing the name and corresponding DAQ device channels to write output
            to. The keys are user-facing names of the output sources and the values are the
            corresponding channel in the form of a tuple `(device, channel)` e.g. `('Dev1','ao0')`.
            Note that multi-device tasks are valid and should be accepted, however the prerequisite
            hardware and NI MAX configuration is required and not managed here.
        device_limits_dict: dict[str, tuple[float, float]]
            A dictionary describing the name and output voltage limits of the corresponding DAQ
            device channels. The key should be a string matching the name given in the
            `device_channels_dict` and the corresponding value should be a tuple of floats where the
            first/second element gives the min/max voltage output allowed.
        '''
        # Run the main initialization
        super().__init__(device_channels_dict=device_channels_dict)
        # Save the device limits dictionary
        self.device_limits_dict = device_limits_dict

    def build(
            self,
            data: dict[str, np.ndarray],
            clock_device: str,
            clock_terminal: str,
            sample_rate: float
    ) -> None:
        '''
        Instantiates the `nidaqmx.Task` corresponding to the output, sets the timing of the task
        (typically utilizing the clock signal), configures the start trigger to begin with the start
        of the clock task. Then writes the data.

        Parameters
        ----------
        data: dict[str, np.ndarray]
            Data to write during the sequence in the form of a dictionary with keys associated to 
            each output and values giving the data to write.
        clock_device: str
            String indicating the device of the clock task generated in the `NidaqSequencer` method
            `NidaqSequencer.run_sequence()`.
        clock_terminal: str
            The terminal for the sequencer clock output to time the source task.
        sample_rate: float
            The sample rate of the outputs. Since the timing source is given by the clock signal,
            this parameter does not directly modify the actual sample rate.
        '''
        try:
            # Validate the data first before continuing. We iterate through the local attribute
            # `device_channels_dict` to ensure that all contained device channels are represented.
            for output_name in self.device_channels_dict:
                self._validate_data(output_name=output_name, data=data[output_name])
            # Save the data to write to the instance, this clears any extra names passed in the data
            self.data = {name: data[name] for name in self.device_channels_dict}
            # Save other parameters
            self.n_samples = np.max([len(data[name]) for name in self.device_channels_dict])
            self.clock_device = clock_device
            self.clock_terminal = clock_terminal
            self.sample_rate = sample_rate

            # Create the task
            self.task = nidaqmx.Task()
            # Create an AO voltage channel for each device channel supplied
            for output_name, (device, channel) in self.device_channels_dict.items():
                self.task.ao_channels.add_ao_voltage_chan(device+'/'+channel)
            # Configure the timing. For now, we are hard-coding in the use of the digital input 
            # sample clock as the timing source and start trigger. In the future it would be better
            # to dynamically program this in by simply passing the "clock task".
            self.task.timing.cfg_samp_clk_timing(
                sample_rate,
                source='/'+clock_device+'/'+clock_terminal,
                sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
                samps_per_chan=self.n_samples
            )
            # Write the data to the task, must be an np.ndarray with shape `n_channels` by 
            # `n_samples` so we reshape it first. Iterating through the `device_channels_dict`
            # ensures that the data is supplied in the same order as the channels were added.
            data_to_write = np.array([self.data[name] for name in self.device_channels_dict])
            # Then create a writer and set the data
            self.writer = nidaqmx.stream_writers.AnalogMultiChannelWriter(self.task.out_stream)
            self.writer.write_many_sample(data=data_to_write, timeout=self.n_samples/sample_rate + 1)
            # Commit the task to the hardware
            self.task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)
        # Try to catch errors relating to multi-device approaches
        except (nidaqmx.errors.DaqResourceWarning, nidaqmx.errors.DaqWriteError) as e:
            raise RuntimeError(f'A DAQ error occured possibly relating to multi-device setup: {e}')
        # Raise any other errors
        except Exception as e:
            raise e

    def set(
            self,
            output_name: str,
            setpoint: Union[float, int, bool]
    ) -> None:
        '''
        A utility method for setting the value of the output channel to the `setpoint` outside of 
        the sequence. This can be done for initialization.

        Parameters
        ----------
        output_name: str
            The name of the output channel to set.
        setpoint: float | int | bool
            Value to set the output channel to.
        '''
        # Verifty the setpoint is in range
        self._validate_data(output_name=output_name, data=setpoint)
        # Get the device and channel for the output
        device, channel = self.device_channels_dict[output_name]
        # Create a task on the voltage output, write the desired voltage
        with nidaqmx.Task() as task:
            task.ao_channels.add_ao_voltage_chan(device+'/'+channel)
            task.write(setpoint)

    def _validate_data(
            self,
            output_name: str,
            data: Union[float, int, np.ndarray]
    ) -> None:
        '''
        Checks if the provided `data` is valid output for the specified output channel.

        Parameters
        ----------
        output_name: str
            Name of the output channel to verify data against.
        data: float | int | np.ndarray
            Some data to validate.
        '''
        # Get the limits for the specified channels
        limits = self.device_limits_dict[output_name]
        try:
            data = np.array(data)
        except:
            raise TypeError(f'Data type {type(data).__name__} is not a valid type.')
        if np.any(data < self.device_limits_dict[output_name][0]):
            raise ValueError(f'Data contains points less than allowed minimum {limits[0]:.3f}.')
        if np.any(data > self.device_limits_dict[output_name][1]):
            raise ValueError(f'Data contains points greater than allowed maximum {limits[1]:.3f}.')
        

