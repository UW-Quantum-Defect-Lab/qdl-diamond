import logging
import nidaqmx.stream_readers
import numpy as np

import nidaqmx
import nidaqmx.constants
import nidaqmx.errors
import nidaqmx.stream_writers

# Because we are on Python 3.9 type union operator `|` is not yet implemented
from typing import Union, Any


class NidaqSequencerInputGroup:

    def __init__(
            self,
            channels_config: dict[str, dict[str,Any]],
            **kwargs
    ) -> None:
        '''
        Parameters
        ----------
        channels_config: dict[str, dict[str,Any]]
            A dictionary describing the channels included in the input group. The keys are the
            user-facing names of the input channels while the values are dictionaries describing the
            channel configuration. This "channel-configuration dictionary" should have the
            appropriate key-value pairs for the type of input source, as specified by the relevant
            child classes. In general, the channel-configuraiton dictionary should at least specify
            the device and physical/software channel of the channel, e.g.
            ```
                {'device': 'Dev1', 'channel': 'ai0'}
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
            channels_config: dict[str, dict[str,Any]]
    ) -> None:
        '''
        Parameters
        ----------
        channels_config: dict[str, dict[str,Any]]
            A dictionary describing the input channels to be included. The keys should be
            user-facing names identifying the channels (e.g. "photodiode") and the values describe
            the configuration of the channel. The channel configuration requires two items for the
            `device` and physical/digital `channel` respectively, e.g. 
            ```
                {'device': 'Dev1', 'channel': 'ai0'}
            ```
            Finally, note that multi-device tasks are valid and should be accepted, however the
            prerequisite hardware and NI MAX configuration is required and not managed here.
        '''
        # Run the main initialization
        super().__init__(channels_config=channels_config)

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
            self.n_samples = {name: n_samples[name] for name in self.channels_config}
            self.readout_delays = {name: readout_delays[name] for name in self.channels_config}


            # Determine the number of samples the task should run for. Should be the max of the
            # `n_samples + readout_delays`.
            self.n_samples_in_task = np.max([n_samples[name] + readout_delays[name] for name in self.channels_config])

            # Create task
            self.task = nidaqmx.Task()
            # Create an AI voltage channel for each channel supplied
            for input_name, config in self.channels_config.items():
                self.task.ai_channels.add_ai_voltage_chan(config['device']+'/'+config['channel'])
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
        idxs = {name: (self.readout_delays[name], self.readout_delays[name]+self.n_samples[name]) for name in self.channels_config}
        # Write data to dictionary. Enumerates over the `device_channels_dict` to associate each
        # row in the data buffer with a given input source. Only takes data after the readout delay.
        self.data = {
            name: data_buffer[j,idxs[name][0]:idxs[name][1]] for j, name in enumerate(self.channels_config)
        }


class NidaqSequencerCIEdgeGroup(NidaqSequencerInputGroup):

    def __init__(
            self,
            channels_config: dict[str, dict[str,Any]]
    ) -> None:
        '''
        Parameters
        ----------
        channels_config: dict[str, dict[str,Any]]
            A dictionary describing the input channels to be included. The keys should be
            user-facing names identifying the channels (e.g. "photodiode") and the values describe
            the configuration of the channel. The channel configuration requires three items for the
            `device`, `channel`, and `terminal` respectively, e.g. 
            ```
                {'device': 'Dev1', 'channel': 'ai0', 'terminal': 'PFI0}
            ```
            Finally, note that multi-device tasks are valid and should be accepted, however the
            prerequisite hardware and NI MAX configuration is required and not managed here.
        '''
        # Run the main initialization
        super().__init__(channels_config=channels_config)

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
            self.n_samples = {name: n_samples[name] for name in self.channels_config}
            self.readout_delays = {name: readout_delays[name] for name in self.channels_config}

            # Create task
            self.task = nidaqmx.Task()
            # Determine the number of samples the task should run for. Should be the max of the
            # `n_samples + readout_delays`.
            self.n_samples_in_task = np.max([n_samples[name] + readout_delays[name] for name in self.channels_config])

            # Create an CI edge counting channel for each input source
            for input_name, config in self.channels_config.items():
                # Create the channel
                ci_channel = self.task.ci_channels.add_ci_count_edges_chan(
                    config['device']+'/'+config['channel'],
                    initial_count=0,
                    count_direction=nidaqmx.constants.CountDirection.COUNT_UP,
                    edge=nidaqmx.constants.Edge.RISING
                )
                # Configure the physical terminal for the input signal to count
                ci_channel.ci_count_edges_term = '/'+config['device']+'/'+config['terminal']
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
        idxs = {name: (self.readout_delays[name], self.readout_delays[name]+self.n_samples[name]) for name in self.channels_config}
        # Get the data output for each input and populate data dictionary
        self.data = {}
        for j, name in enumerate(self.channels_config):
            # Get the data points of interest and subtract the counts just prior
            self.data[name] = data_buffer[j,idxs[name][0]:idxs[name][1]]-data_buffer[j,(idxs[name][0])]


class NidaqSequencerCIEdgeRateGroup(NidaqSequencerInputGroup):

    '''
    Same as `NidaqSequencerCIEdgeGroup` but returns the count rate rather than the total number of
    counts.
    '''

    def __init__(
            self,
            channels_config: dict[str, dict[str,Any]]
    ) -> None:
        '''
        Parameters
        ----------
        channels_config: dict[str, dict[str,Any]]
            A dictionary describing the input channels to be included. The keys should be
            user-facing names identifying the channels (e.g. "photodiode") and the values describe
            the configuration of the channel. The channel configuration requires three items for the
            `device`, `channel`, and `terminal` respectively, e.g. 
            ```
                {'device': 'Dev1', 'channel': 'ai0', 'terminal': 'PFI0}
            ```
            Finally, note that multi-device tasks are valid and should be accepted, however the
            prerequisite hardware and NI MAX configuration is required and not managed here.
        '''
        # Run the main initialization
        super().__init__(channels_config=channels_config)

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
            self.n_samples = {name: n_samples[name] for name in self.channels_config}
            self.readout_delays = {name: readout_delays[name] for name in self.channels_config}

            # Create task
            self.task = nidaqmx.Task()
            # Determine the number of samples the task should run for. Should be the max of the
            # `n_samples + readout_delays`. Add an extra sample
            self.n_samples_in_task = np.max([n_samples[name] + readout_delays[name] for name in self.channels_config]) + 1

            # Create an CI edge counting channel for each input source
            for input_name, config in self.channels_config.items():
                # Create the channel
                ci_channel = self.task.ci_channels.add_ci_count_edges_chan(
                    config['device']+'/'+config['channel'],
                    initial_count=0,
                    count_direction=nidaqmx.constants.CountDirection.COUNT_UP,
                    edge=nidaqmx.constants.Edge.RISING
                )
                # Configure the physical terminal for the input signal to count
                ci_channel.ci_count_edges_term = '/'+config['device']+'/'+config['terminal']
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
        idxs = {name: (self.readout_delays[name], self.readout_delays[name]+self.n_samples[name]+1) for name in self.channels_config}
        # Get the data output for each input and populate data dictionary
        self.data = {}
        for j, name in enumerate(self.channels_config):
            # Get the data points of interest, take the difference, scale by the sample rate to get
            # the rate in counts per second.
            self.data[name] = np.diff(data_buffer[j,idxs[name][0]:idxs[name][1]]) * self.sample_rate
