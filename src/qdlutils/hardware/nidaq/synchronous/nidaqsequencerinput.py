import logging
import numpy as np
import nidaqmx
import nidaqmx.constants
import nidaqmx.stream_readers

class NidaqSequencerInput:

    def __init__(
            self,
            name: str,
            device: str,
            channel: str,
            **kwargs
    ) -> None:
        self.name = name
        self.device = device
        self.channel = channel

        self.task = None
        self.data = None
        self.clock_device = None
        self.sample_rate = None
        self.n_samples = None
        self.readout_delay = None
    
    def build(
            self,
            n_samples,
            clock_device,
            sample_rate,
            readout_delay
    ) -> None:
        pass

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
    



class NidaqSequencerAIVoltage(NidaqSequencerInput):

    def __init__(
            self,
            name: str,
            device: str,
            channel: str,
    ) -> None:
        self.name = name
        self.device = device
        self.channel = channel

        self.task = None
        self.data = None
        self.clock_device = None
        self.sample_rate = None
        self.n_samples = None
        self.readout_delay = None

    def build(
            self,
            n_samples: int,
            clock_device: str,
            sample_rate: float,
            readout_delay: int = 0
    ):
        
        # Save parameters
        self.clock_device = clock_device
        self.sample_rate = sample_rate
        self.n_samples = n_samples
        self.readout_delay = readout_delay

        # Create task
        self.task = nidaqmx.Task()
        # Create the AI voltage channel and configure the timing
        self.task.ai_channels.add_ai_voltage_chan(self.device + '/' + self.channel)
        self.task.timing.cfg_samp_clk_timing(
            self.sample_rate,
            source='/'+self.clock_device+'/di/SampleClock',
            sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
            samps_per_chan=self.n_samples+self.readout_delay
        )
        # Configure the trigger for the AI task
        self.task.triggers.start_trigger.cfg_dig_edge_start_trig(
            '/'+self.clock_device+'/di/StartTrigger'
        )
        # Commit the task to the hardware
        self.task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)

    def readout(
            self
    ) -> np.ndarray:
        self.data = self.task.read(
            number_of_samples_per_channel=self.n_samples+self.readout_delay
        )[self.readout_delay:]
        return self.data
    



class NidaqSequencerCIEdge(NidaqSequencerInput):

    def __init__(
            self,
            name: str,
            device: str,
            channel: str,
            terminal: str,
    ) -> None:
        self.name = name
        self.device = device
        self.channel = channel
        self.terminal = terminal

        self.task = None
        self.data = None
        self.clock_device = None
        self.sample_rate = None
        self.n_samples = None
        self.readout_delay = None

    def build(
            self,
            n_samples: int,
            clock_device: str,
            sample_rate: float,
            readout_delay: int = 0
    ):
        
        # Save parameters
        self.clock_device = clock_device
        self.sample_rate = sample_rate
        self.n_samples = n_samples
        self.readout_delay = readout_delay

        # Create task
        self.task = nidaqmx.Task()
        # Create the counter input channel
        ci_channel = self.task.ci_channels.add_ci_count_edges_chan(
            self.device+'/'+self.channel,
            initial_count=0,
            count_direction=nidaqmx.constants.CountDirection.COUNT_UP,
            edge=nidaqmx.constants.Edge.RISING
        )
        # Configure the terminal for the signal to count
        ci_channel.ci_count_edges_term = '/'+self.device+'/'+self.terminal
        # Configure the timing
        self.task.timing.cfg_samp_clk_timing(
            self.sample_rate,
            source='/'+self.clock_device+'/di/SampleClock',
            active_edge=nidaqmx.constants.Edge.RISING,
            sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
            samps_per_chan=self.n_samples+self.readout_delay
        )
        # Arm the start trigger
        self.task.triggers.arm_start_trigger.trig_type = nidaqmx.constants.TriggerType.DIGITAL_EDGE
        self.task.triggers.arm_start_trigger.dig_edge_edge = nidaqmx.constants.Edge.RISING
        self.task.triggers.arm_start_trigger.dig_edge_src = '/'+self.clock_device+'/di/SampleClock'
        # Set the counter buffer size
        self.task.in_stream.input_buf_size = self.n_samples+self.readout_delay
        # Commit the task to the hardware
        self.task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)

        # Prepare the counter reader for the ci_task
        self.reader = nidaqmx.stream_readers.CounterReader(self.task.in_stream)

    def readout(
            self
    ) -> np.ndarray:
        
        # Get the counter data via the I/O stream
        data_buffer = np.zeros(self.n_samples+self.readout_delay,dtype=np.uint32)
        self.reader.read_many_sample_uint32(
            data_buffer,
            number_of_samples_per_channel=self.n_samples+self.readout_delay
        )
        # Get the data after the delay, subtracking the counts at the end of the delay
        if self.readout_delay > 0:
            self.data = data_buffer[self.readout_delay:] - data_buffer[self.readout_delay-1]
        else:
            self.data = data_buffer

        return self.data