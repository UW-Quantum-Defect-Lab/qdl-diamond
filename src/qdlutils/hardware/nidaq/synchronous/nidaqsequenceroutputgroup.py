import logging
import numpy as np

import nidaqmx
import nidaqmx.constants
import nidaqmx.errors
import nidaqmx.stream_writers

# Because we are on Python 3.9 type union operator `|` is not yet implemented
from typing import Union, Any

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
            channels_config: dict[str, dict[str,Any]],
            **kwargs
    ) -> None:
        '''
        Parameters
        ----------
        channels_config: dict[str, dict[str,Any]]
            A dictionary describing the channels included in the output group. The keys are the
            user-facing names of the input channels while the values are dictionaries describing the
            channel configuration. This "channel-configuration dictionary" should have the
            appropriate key-value pairs for the type of output source, as specified by the relevant
            child classes. In general, the channel-configuraiton dictionary should at least specify
            the device and physical/software channel of the channel, e.g.
            ```
                {'device': 'Dev1', 'channel': 'ao0'}
            ```
            Note that the this class and higher-level functions rely on the ordered nature of the
            dictionary and so internal methods should not modify this input after initialization.
            Finally, note that multi-device tasks are valid and should be accepted, however the
            prerequisite hardware and NI MAX configuration is required and not managed here.
        **kwargs:
            Any number of keyword arguments required for specific output implementations.
        '''
        self.channels_config = channels_config
        self.n_channels = len(channels_config)
        self.channel_names = [name for name in channels_config]

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
            channels_config: dict[str, dict[str,Any]]
    ) -> None:
        '''
        Parameters
        ----------
        channels_config: dict[str, dict[str,Any]]
            A dictionary describing the output channels to be included. The keys should be
            user-facing names identifying the channels (e.g. "scan_laser") and the values describe
            the configuration of the channel. The channel configuration requires four items for the
            `device`, `channel`, `min`/`max` output values respectively, e.g. 
            ```
                {'device': 'Dev1', 'channel': 'ao0', 'min': -5, 'max': 5}
            ```
            Finally, note that multi-device tasks are valid and should be accepted, however the
            prerequisite hardware and NI MAX configuration is required and not managed here.
        '''
        # Run the main initialization
        super().__init__(channels_config=channels_config)

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
            for output_name in self.channels_config:
                self._validate_data(output_name=output_name, data=data[output_name])
            # Save the data to write to the instance, this clears any extra names passed in the data
            self.data = {name: data[name] for name in self.channels_config}
            # Save other parameters
            self.n_samples = np.max([len(data[name]) for name in self.channels_config])
            self.clock_device = clock_device
            self.clock_terminal = clock_terminal
            self.sample_rate = sample_rate

            # Create the task
            self.task = nidaqmx.Task()
            # Create an AO voltage channel for each device channel supplied
            for output_name, config in self.channels_config.items():
                self.task.ao_channels.add_ao_voltage_chan(config['device']+'/'+config['channel'])
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
            data_to_write = np.array([self.data[name] for name in self.channels_config])
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
        config = self.channels_config[output_name]
        # Create a task on the voltage output, write the desired voltage
        with nidaqmx.Task() as task:
            task.ao_channels.add_ao_voltage_chan(config['device']+'/'+config['channel'])
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
        config = self.channels_config[output_name]
        min = config['min']
        max = config['max']
        try:
            data = np.array(data)
        except:
            raise TypeError(f'Data type {type(data).__name__} is not a valid type.')
        if np.any(data < min):
            raise ValueError(f'Data contains points less than allowed minimum {min:.3f}.')
        if np.any(data > max):
            raise ValueError(f'Data contains points greater than allowed maximum {max:.3f}.')
        


class NidaqSequencerDO32LineGroup(NidaqSequencerOutputGroup):

    '''
    This class represents the controller for `NidaqSequencer` 32-bit digital output line control.

    Internally the implementation of this class is distinct from the analog output in that the
    individual output "channels" are actually implemented as a single channel which controls all 
    lines simultaneously. This is necessary as `nidaqmx` does not implement a stream writer with
    partiy to the analog output's `write_many_sample()` method.
    This is all handled internally and the user should not expect any different behavior, although
    generating large streams of data can result in slowed initialization. Developers should be aware
    as re-building the output group can accumulate delays.
    '''

    def __init__(
            self,
            channels_config: dict[str, dict[str,Any]]
    ) -> None:
        '''
        Parameters
        ----------
        channels_config: dict[str, dict[str,Any]]
            A dictionary describing the output channels to be included. The keys should be
            user-facing names identifying the channels (e.g. "scan_laser") and the values describe
            the configuration of the channel. The channel configuration requires four items for the
            `device`, `port`, `line` and `port_size` respectively, e.g. 
            ```
                {'device': 'Dev1', 'port': 'port0', 'line': 'line7'}
            ```
            This creates a "channel" on 'Dev1/port0/line7' where 'port0' has a size of of 32 bits. 
            As noted above, each of the lines can represent individual devices, however when run,
            the code will initialize and process data on ALL lines in the specified port
            simultaneously as a single channel. As a result, any lines not specified in the config 
            will be set to FALSE (TTL Low, or 0 V) during and after the sequence has been executed. 
            Users should take care to include all relevant hardware in the DO line group as this may
            lead to unexpected flipping of the state for any unincluded hardware.

            Finally, note that multi-device tasks are valid and should be accepted, however the
            prerequisite hardware and NI MAX configuration is required and not managed here.
        '''
        # Run the main initialization
        super().__init__(channels_config=channels_config)

        # Because the data is ultimately structured as a group of ports we need to first group the
        # channels (lines) by their respective ports.
        # Get all unique ports for all provided channels.
        self.ports = set([config['device']+'/'+config['port'] for config in self.channels_config.values()])
        # Separate the lines into groups specified by their port
        self.port_line_groups = {port: [] for port in self.ports}
        for channel,config in self.channels_config.items():
            self.port_line_groups[config['device']+'/'+config['port']].append(channel)
        # Blank dictionary to store the port-structured data to actually write to the DAQ
        self.port_data = {}

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
            each output and values giving the data to write. Data to write in this case should be a
            vector containing only integers 0 or 1.
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
            for output_name in self.channels_config:
                self._validate_data(output_name=output_name, data=data[output_name])
            # Save the data to write to the instance, this clears any extra names passed in the data
            self.data = {name: data[name] for name in self.channels_config}
            # Save other parameters
            self.n_samples = np.max([len(data[name]) for name in self.channels_config])
            self.clock_device = clock_device
            self.clock_terminal = clock_terminal
            self.sample_rate = sample_rate

            # Restructure data for port output
            self._convert_line_data_to_port_data()

            # Create the task
            self.task = nidaqmx.Task()
            # Create a channel for each port
            for port in self.ports:
                # Add the DO channel for each port
                self.task.do_channels.add_do_chan(
                    port, 
                    line_grouping=nidaqmx.constants.LineGrouping.CHAN_FOR_ALL_LINES
                )
            # Configure the timing
            self.task.timing.cfg_samp_clk_timing(
                sample_rate,
                source='/'+clock_device+'/'+clock_terminal,
                sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
                samps_per_chan=self.n_samples
            )
            # Write the data to the task
            data_to_write = np.array([self.port_data[port] for port in self.ports],)
            # Then create a writer and set the data
            self.writer = nidaqmx.stream_writers.DigitalMultiChannelWriter(self.task.out_stream)
            self.writer.write_many_sample_port_uint32(data=data_to_write, timeout=self.n_samples/sample_rate + 1)
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
        config = self.channels_config[output_name]
        # Create a task on the voltage output, write the desired voltage
        with nidaqmx.Task() as task:
            task.do_channels.add_do_chan(config['device']+'/'+config['port']+'/'+config['line'], 
                                         line_grouping=nidaqmx.constants.LineGrouping.CHAN_PER_LINE)
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
        try:
            data = np.array(data, dtype=np.uint8)
        except:
            raise TypeError(f'Data type {type(data).__name__} is not a valid type.')
        # Scan the data for any values that are not 0 or 1
        mask = (data != 0) & (data != 1)
        # If any entries in mask are True then a non-binary entry is detected
        if np.any(mask):
            raise ValueError('Data contains values other than 0 or 1')
        
        
    def _convert_line_data_to_port_data(
            self,
    ):
        '''
        Converts the individual line data to a port-structured output scheme.

        For example, if the requested data stream is
        ```
            port0/line0 : [1, 0, 1]
            port0/line2 : [0, 1, 1]
            port1/line1 : [0, 1, 1]
         ```
        this method converts this two two data streams: one for `port0` and a second for `port1`
        given by
        ```
            port0       : 2^0*[1,0,1] + 2^2*[0,1,1] = [1,4,5]
            port1       : 2^1*[0,1,1]               = [0,2,2]
        ```
        The port-facing data streams are saved in the class attribute `self.port_data`.
        '''
        for port,lines in self.port_line_groups.items():
            # Empty vector to hold the data for the given port
            data = np.zeros(self.n_samples, dtype=np.uint32)
            # Iterate through the lines in the port and add the relevant bits to each sample
            for channel in lines:
                # Get the line number (all numbers XYZ for 'lineXYZ')
                line_num = int(((self.channels_config[channel])['line'])[4:])
                # Scale data for the line by the line number bit and add to the data
                data += np.array((2**line_num)*self.data[channel], dtype=np.uint32)
            # Save the port data
            self.port_data[port] = data
