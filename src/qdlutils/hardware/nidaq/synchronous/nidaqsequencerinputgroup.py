import logging
import nidaqmx.stream_readers
import numpy as np

import nidaqmx
import nidaqmx.constants
import nidaqmx.errors
import nidaqmx.stream_writers

# Because we are on Python 3.9 type union operator `|` is not yet implemented
from typing import Union


class NidaqSequencerInputGroup:

    def __init__(
            self,
            device_channels_dict: dict[str, tuple[str,str]],
            **kwargs
    ) -> None:
        '''
        Parameters
        ----------
        device_channels_dict: dict[str, tuple[str,str]]
            A dictionary describing the name and corresponding DAQ device channels to read input
            from. The keys are user-facing names of the input sources and the values are the
            corresponding channel in the form of a tuple `(device, channel)` e.g. `('Dev1','ai0')`.

            Note that the implementation of digital inputs will require modifications to the base
            structure of this class due to the `NidaqSequencer`s use of the digital input channel to
            generate the clock task. 

            *** A next step will be to modify the sequencer to utilize a counter out signal on the appropriate counter out channel as the clock.

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
        self.data = None
        self.clock_device = None
        self.sample_rate = None
        self.n_samples = None
        self.readout_delays = None
        self.n_samples_in_task = None
    
    def build(
            self,
            n_samples: dict[str,int],
            clock_device: str,
            clock_terminal: str,
            sample_rate: float,
            readout_delays: dict[str,int],
    ) -> None:
        '''
        Parameters
        ----------
        n_samples: dict[str,int]
            A dictionary describing the number of samples to collect on each input source.
        clock_device: str
            The device on which the clock is located, generally the same device as all associated
            inputs.
        clock_terminal: str
            The terminal for the sequencer clock output to time the source task.
        sample_rate: float
            The sample rate of the inputs. Since the timing source is given by the clock signal,
            this parameter does not directly modify the actual sample rate.
        readout_delays: dict[str,int]
            A dictionary describing the number of samples to delay the start of the data collection
            for each input source.
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

    def readout(
            self,
            **kwargs
    ):
        return self.data
    
    def close(
            self
    ):
        self.task.stop()
        self.task.close()
    

class NidaqSequencerAIVoltageGroup(NidaqSequencerInputGroup):

    def __init__(
            self,
            device_channels_dict: dict[str, tuple[str,str]]
    ) -> None:
        # Run the main initialization
        super().__init__(device_channels_dict=device_channels_dict)

    def build(
            self,
            n_samples: dict[str,int],
            clock_device: str,
            clock_terminal: str,
            sample_rate: float,
            readout_delays: dict[str,int],
    ) -> None:
        '''
        Parameters
        ----------
        n_samples: dict[str,int]
            A dictionary describing the number of samples to collect on each input source.
        clock_device: str
            The device on which the clock is located, generally the same device as all associated
            inputs.
        clock_terminal: str
            The terminal for the sequencer clock output to time the source task.
        sample_rate: float
            The sample rate of the inputs. Since the timing source is given by the clock signal,
            this parameter does not directly modify the actual sample rate.
        readout_delays: dict[str,int]
            The number of clock cycles (samples) to delay the readout from the inputs.
        '''
        try:
            # Save parameters
            self.clock_device = clock_device
            self.clock_terminal = clock_terminal
            self.sample_rate = sample_rate
            # Keep only the samples and delays relevant to this input group
            self.n_samples = {name: n_samples[name] for name in self.device_channels_dict}
            self.readout_delays = {name: readout_delays[name] for name in self.device_channels_dict}


            # Determine the number of samples the task should run for. Should be the max of the
            # `n_samples + readout_delays`.
            self.n_samples_in_task = np.max([n_samples[name] + readout_delays[name] for name in self.device_channels_dict])

            # Create task
            self.task = nidaqmx.Task()
            # Create an AI voltage channel for each channel supplied
            for input_name, (device, channel) in self.device_channels_dict.items():
                self.task.ai_channels.add_ai_voltage_chan(device+'/'+channel)
            # Configure the timing. For now, we are hard-coding in the use of the digital input 
            # sample clock as the timing source and start trigger. In the future it would be better
            # to dynamically program this in by simply passing the "clock task".
            self.task.timing.cfg_samp_clk_timing(
                sample_rate,
                source='/'+clock_device+'/'+clock_terminal,
                sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
                samps_per_chan=self.n_samples_in_task
            )
            # Create the reader
            self.reader = nidaqmx.stream_readers.AnalogMultiChannelReader(self.task.in_stream)
            # Commit the task to the hardware
            self.task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)
        # Try to catch errors relating to multi-device approaches
        except (nidaqmx.errors.DaqResourceWarning, nidaqmx.errors.DaqReadError) as e:
            raise RuntimeError(f'A DAQ error occured possibly relating to multi-device setup: {e}')
        # Raise any other errors
        except Exception as e:
            raise e

    def readout(
            self
    ) -> None:
        # Get the output data
        data_buffer = np.zeros(shape=(self.n_channels,self.n_samples_in_task))
        # Squeeze the data buffer if only one channel provided (commented out here -- seems like a bug?)
        #if self.n_channels < 2:
        #    data_buffer = data_buffer.squeeze()
        self.reader.read_many_sample(
            data=data_buffer,
            number_of_samples_per_channel=self.n_samples_in_task,
            timeout=self.n_samples_in_task/self.sample_rate + 1)
        # Reshape the output data to match 2-d array
        data_buffer = data_buffer.reshape((self.n_channels,self.n_samples_in_task))
        # The start and stop index for data collection
        idxs = {name: (self.readout_delays[name], self.readout_delays[name]+self.n_samples[name]) for name in self.device_channels_dict}
        # Write data to dictionary. Enumerates over the `device_channels_dict` to associate each
        # row in the data buffer with a given input source. Only takes data after the readout delay.
        self.data = {
            name: data_buffer[j,idxs[name][0]:idxs[name][1]] for j, name in enumerate(self.device_channels_dict)
        }


class NidaqSequencerCIEdgeGroup(NidaqSequencerInputGroup):

    def __init__(
            self,
            device_channels_dict: dict[str, tuple[str,str]],
            device_terminals_dict: dict[str, str]
    ) -> None:
        '''
        Parameters
        ----------
        device_channels_dict: dict[str, tuple[str,str]]
            A dictionary describing the name and corresponding DAQ device channels to read input
            from. The keys are user-facing names of the input sources and the values are the
            corresponding channel in the form of a tuple `(device, channel)` e.g. `('Dev1','ai0')`.

            *** A next step will be to modify the sequencer to utilize a counter out signal on the appropriate counter out channel as the clock.

        device_terminals_dict: dict[str, tuple[str,str]]
            A dictionary describing the name and corresponding physical DAQ terminals to perform 
            edge counting on. The keys are user-facing names of the input sources and the values are
            the corresponding terminal in the form of a tuple `(device, terminal)`,
            e.g. `('Dev1','PFI0')`.
        '''
        # Run the main initialization
        super().__init__(device_channels_dict=device_channels_dict)
        # Save the terminals
        self.device_terminals_dict = device_terminals_dict

    def build(
            self,
            n_samples: dict[str,int],
            clock_device: str,
            clock_terminal: str,
            sample_rate: float,
            readout_delays: dict[str,int],
    ) -> None:
        '''
        Parameters
        ----------
        n_samples: dict[str,int]
            Number of samples for the inputs to record.
        clock_device: str
            The device on which the clock is located, generally the same device as all associated
            inputs.
        clock_terminal: str
            The terminal for the sequencer clock output to time the source task.
        sample_rate: float
            The sample rate of the inputs. Since the timing source is given by the clock signal,
            this parameter does not directly modify the actual sample rate.
        readout_delay: dict[str,int]
            The number of clock cycles (samples) to delay the readout from the inputs.
        '''
        try:
            # Save parameters
            self.clock_device = clock_device
            self.clock_terminal = clock_terminal
            self.sample_rate = sample_rate
            # Keep only the samples and delays relevant to this input group
            self.n_samples = {name: n_samples[name] for name in self.device_channels_dict}
            self.readout_delays = {name: readout_delays[name] for name in self.device_channels_dict}

            # Create task
            self.task = nidaqmx.Task()
            # Determine the number of samples the task should run for. Should be the max of the
            # `n_samples + readout_delays`.
            self.n_samples_in_task = np.max([n_samples[name] + readout_delays[name] for name in self.device_channels_dict])

            # Create an CI edge counting channel for each input source
            for input_name, (device, channel) in self.device_channels_dict.items():
                # Create the channel
                ci_channel = self.task.ci_channels.add_ci_count_edges_chan(
                    device+'/'+channel,
                    initial_count=0,
                    count_direction=nidaqmx.constants.CountDirection.COUNT_UP,
                    edge=nidaqmx.constants.Edge.RISING
                )
                # Configure the physical terminal for the input signal to count
                terminal = self.device_terminals_dict[input_name]
                ci_channel.ci_count_edges_term = '/'+device+'/'+terminal
            # Configure the timing.
            self.task.timing.cfg_samp_clk_timing(
                self.sample_rate,
                source='/'+clock_device+'/'+clock_terminal,
                active_edge=nidaqmx.constants.Edge.RISING,
                sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
                samps_per_chan=self.n_samples_in_task
            )
            # Set the counter buffer size
            self.task.in_stream.input_buf_size = self.n_samples_in_task
            # Prepare the counter reader
            self.reader = nidaqmx.stream_readers.CounterReader(self.task.in_stream)
            # Commit the task to the hardware
            self.task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)
            
        # Try to catch errors relating to multi-device approaches
        except (nidaqmx.errors.DaqResourceWarning, nidaqmx.errors.DaqReadError) as e:
            raise RuntimeError(f'A DAQ error occured possibly relating to multi-device setup: {e}')
        # Raise any other errors
        except Exception as e:
            raise e

    def readout(
            self
    ) -> None:
        '''
        Notes
        -----
        The readout method for this type of detection scheme is somewhat nuanced and some care must
        be taken in order to properly interpret the data this class produces. Specifically, the edge
        counter counts the number of rising edges from the start of the task. Due to the quirks of
        `nidaqmx`, it does not seem possible to trigger the start of this task with the counter
        directly (although passing the counter signal itself might work). As a consequence, the task
        will have already accumulated some counts prior to the first sample in a given sequence.
        However, the amount of counts depends on the time between the start and first clock cycle
        and so the rate is uncertain (software-overhead-limited). To correct for this, the first
        sample value is subtracted uniformly from all samples such that the first sample in the data
        reads 0. This is applied even for nonzero readout delay. In this way the data at a given
        sample reflects the number of counts obtained since the first sample.

        Note that this convention is done to provide as similar behavior to the base edge counter
        channel in `nidaqmx`. In cases where the number of detection events between samples is of 
        interest utilize the `NidaqSequencerCIEdgeRateGroup` class.
        '''
        # Get the output data
        data_buffer = np.zeros(shape=(self.n_channels,self.n_samples_in_task),dtype=np.uint32)
        # Squeeze data buffer if only one channel 
        # (this seems like a bug with nidaqmx as the AI reader buffer seems to want a (1,n) instead of (n,)...)
        if self.n_channels < 2:
            data_buffer = data_buffer.squeeze()
        self.reader.read_many_sample_uint32(
            data=data_buffer,
            number_of_samples_per_channel=self.n_samples_in_task,
            timeout=self.n_samples_in_task/self.sample_rate + 1)
        # Reshape the output data to match 2-d array
        data_buffer = data_buffer.reshape((self.n_channels,self.n_samples_in_task))
        # Determine the start and stop index for data collection. Because the edge counter returns 
        # the number of counts since the start of the task, the data for the first entry will 
        # generically be non-zero (due to some lag between the start of the task and the first clock
        # cycle). To fix this we simply just subtract, from all samples, the value of the first.
        idxs = {name: (self.readout_delays[name], self.readout_delays[name]+self.n_samples[name]) for name in self.device_channels_dict}
        # Get the data output for each input and populate data dictionary
        self.data = {}
        for j, name in enumerate(self.device_channels_dict):
            # Get the data points of interest and subtract the counts just prior
            self.data[name] = data_buffer[j,idxs[name][0]:idxs[name][1]]-data_buffer[j,(idxs[name][0])]


class NidaqSequencerCIEdgeRateGroup(NidaqSequencerInputGroup):

    '''
    Same as `NidaqSequencerCIEdgeGroup` but returns the count rate rather than the total number of
    counts.
    '''

    def __init__(
            self,
            device_channels_dict: dict[str, tuple[str,str]],
            device_terminals_dict: dict[str, str]
    ) -> None:
        '''
        Parameters
        ----------
        device_channels_dict: dict[str, tuple[str,str]]
            A dictionary describing the name and corresponding DAQ device channels to read input
            from. The keys are user-facing names of the input sources and the values are the
            corresponding channel in the form of a tuple `(device, channel)` e.g. `('Dev1','ai0')`.

            *** A next step will be to modify the sequencer to utilize a counter out signal on the appropriate counter out channel as the clock.

        device_terminals_dict: dict[str, tuple[str,str]]
            A dictionary describing the name and corresponding physical DAQ terminals to perform 
            edge counting on. The keys are user-facing names of the input sources and the values are
            the corresponding terminal in the form of a tuple `(device, terminal)`,
            e.g. `('Dev1','PFI0')`.
        '''
        # Run the main initialization
        super().__init__(device_channels_dict=device_channels_dict)
        # Save the terminals
        self.device_terminals_dict = device_terminals_dict

    def build(
            self,
            n_samples: dict[str,int],
            clock_device: str,
            clock_terminal: str,
            sample_rate: float,
            readout_delays: dict[str,int],
    ) -> None:
        '''
        Parameters
        ----------
        n_samples: dict[str,int]
            Number of samples for the inputs to record.
        clock_device: str
            The device on which the clock is located, generally the same device as all associated
            inputs.
        clock_terminal: str
            The terminal for the sequencer clock output to time the source task.
        sample_rate: float
            The sample rate of the inputs. Since the timing source is given by the clock signal,
            this parameter does not directly modify the actual sample rate.
        readout_delay: dict[str,int]
            The number of clock cycles (samples) to delay the readout from the inputs.

        Notes
        -----
        We collect one additional sample on top of the `n_samples` and take the difference after to
        get the number of counts between each sample.
        '''
        try:
            # Save parameters
            self.clock_device = clock_device
            self.clock_terminal = clock_terminal
            self.sample_rate = sample_rate
            # Keep only the samples and delays relevant to this input group
            self.n_samples = {name: n_samples[name] for name in self.device_channels_dict}
            self.readout_delays = {name: readout_delays[name] for name in self.device_channels_dict}

            # Create task
            self.task = nidaqmx.Task()
            # Determine the number of samples the task should run for. Should be the max of the
            # `n_samples + readout_delays`. Add an extra sample
            self.n_samples_in_task = np.max([n_samples[name] + readout_delays[name] for name in self.device_channels_dict]) + 1

            # Create an CI edge counting channel for each input source
            for input_name, (device, channel) in self.device_channels_dict.items():
                # Create the channel
                ci_channel = self.task.ci_channels.add_ci_count_edges_chan(
                    device+'/'+channel,
                    initial_count=0,
                    count_direction=nidaqmx.constants.CountDirection.COUNT_UP,
                    edge=nidaqmx.constants.Edge.RISING
                )
                # Configure the physical terminal for the input signal to count
                terminal = self.device_terminals_dict[input_name]
                ci_channel.ci_count_edges_term = '/'+device+'/'+terminal
            # Configure the timing.
            self.task.timing.cfg_samp_clk_timing(
                self.sample_rate,
                source='/'+clock_device+'/'+clock_terminal,
                active_edge=nidaqmx.constants.Edge.RISING,
                sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
                samps_per_chan=self.n_samples_in_task
            )
            # Set the counter buffer size
            self.task.in_stream.input_buf_size = self.n_samples_in_task
            # Prepare the counter reader
            self.reader = nidaqmx.stream_readers.CounterReader(self.task.in_stream)
            # Commit the task to the hardware
            self.task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)
            
        # Try to catch errors relating to multi-device approaches
        except (nidaqmx.errors.DaqResourceWarning, nidaqmx.errors.DaqReadError) as e:
            raise RuntimeError(f'A DAQ error occured possibly relating to multi-device setup: {e}')
        # Raise any other errors
        except Exception as e:
            raise e

    def readout(
            self
    ) -> None:
        '''
        Notes
        -----
        The readout method for this type of detection scheme is somewhat nuanced and some care must
        be taken in order to properly interpret the data this class produces. Specifically, the edge
        counter counts the number of rising edges from the start of the task. Due to the quirks of
        `nidaqmx`, it does not seem possible to trigger the start of this task with the counter
        directly (although passing the counter signal itself might work). As a consequence, the task
        will have already accumulated some counts prior to the first sample in a given sequence.
        However, the amount of counts depends on the time between the start and first clock cycle
        and so the rate is uncertain (software-overhead-limited). To correct for this, the first
        sample value is subtracted uniformly from all samples such that the first sample in the data
        reads 0. This is applied even for nonzero readout delay. In this way the data at a given
        sample reflects the number of counts obtained since the first sample.

        Note that this convention is done to provide as similar behavior to the base edge counter
        channel in `nidaqmx`. In cases where the number of detection events between samples is of 
        interest utilize the `NidaqSequencerCIEdgeRateGroup` class.
        '''
        # Get the output data
        data_buffer = np.zeros(shape=(self.n_channels,self.n_samples_in_task),dtype=np.uint32)
        # Squeeze data buffer if only one channel 
        # (this seems like a bug with nidaqmx as the AI reader buffer seems to want a (1,n) instead of (n,)...)
        if self.n_channels < 2:
            data_buffer = data_buffer.squeeze()
        self.reader.read_many_sample_uint32(
            data=data_buffer,
            number_of_samples_per_channel=self.n_samples_in_task,
            timeout=self.n_samples_in_task/self.sample_rate + 1)
        # Reshape the output data to match 2-d array
        data_buffer = data_buffer.reshape((self.n_channels,self.n_samples_in_task))
        # Determine the start and stop index for data collection. Collect `n_samples+1` starting
        # after the readout delay.
        idxs = {name: (self.readout_delays[name], self.readout_delays[name]+self.n_samples[name]+1) for name in self.device_channels_dict}
        # Get the data output for each input and populate data dictionary
        self.data = {}
        for j, name in enumerate(self.device_channels_dict):
            # Get the data points of interest, take the difference, scale by the sample rate to get
            # the rate in counts per second.
            self.data[name] = np.diff(data_buffer[j,idxs[name][0]:idxs[name][1]]) * self.sample_rate
