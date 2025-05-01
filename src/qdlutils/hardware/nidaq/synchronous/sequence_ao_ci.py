import logging
import numpy as np
import nidaqmx

from qdlutils.hardware.nidaq.synchronous.sequence import Sequence

logger = logging.getLogger(__name__)


class SequenceAOVoltageCIEdge(Sequence):
    '''
    This class implements synchronus analog voltage output (AO) and edge counter input (CI) tasks 
    mediated by an internal clock.
    '''

    def __init__(
            self, 
            ao_device: str = 'Dev1',
            ao_channel: str = 'ao0',
            ci_device: str = 'Dev1',
            ci_channel: str = 'ctr2',
            ci_terminal: str = 'PFI0',
            clock_device: str = 'Dev1',
            clock_channel: str = 'port0',
            ao_min_voltage: float = -5.0,
            ao_max_voltage: float = 5.0,
    ) -> None:
        
        self.ao_device = ao_device
        self.ao_channel = ao_channel
        self.ci_device = ci_device
        self.ci_channel = ci_channel
        self.ci_terminal = ci_terminal
        self.clock_device = clock_device
        self.clock_channel = clock_channel
        self.ao_min_voltage = ao_min_voltage
        self.ao_max_voltage = ao_max_voltage


        # Data vectors and sequence parameters
        self.ao_data = None
        self.ci_data = None
        self.sample_rate = None
        self.soft_start = None
        self.readout_delay = None


    def run_sequence(
            self,
            data: np.ndarray,
            sample_rate: float,
            soft_start: bool = True,
            readout_delay: int = 0
    ):
        # Record sequence settings
        self.ao_data = data
        self.sample_rate = sample_rate
        self.soft_start = soft_start
        self.readout_delay = readout_delay
        
        # Verify the desired voltage is allowed
        self._validate_values(data)

        # Get the number of samples
        n_samples = len(data)

        # If `soft_start` is enabled, set the initial voltage match the first datum in data
        if soft_start:
            self.set_voltage(data[0])

        # Create tasks
        with nidaqmx.Task() as ao_task, nidaqmx.Task() as ci_task, nidaqmx.Task() as clock_task:

            # Create virtual DI clock task on an internal channel
            clock_task.di_channels.add_di_chan(self.clock_device+'/'+self.clock_channel)
            clock_task.timing.cfg_samp_clk_timing(
                sample_rate,
                sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS
            )
            # Commit the clock task to hardware
            clock_task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)

            # Create the AO voltage channel and configure the timing
            ao_task.ao_channels.add_ao_voltage_chan(self.ao_device+'/'+self.ao_channel)
            ao_task.timing.cfg_samp_clk_timing(
                sample_rate,
                source='/'+self.clock_device+'/di/SampleClock',
                sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
                samps_per_chan=n_samples
            )
            # Configure the trigger for the AO task
            ao_task.triggers.start_trigger.cfg_dig_edge_start_trig(
                '/'+self.clock_device+'/di/StartTrigger'
            )

            # Create the counter input channel
            ci_channel = ci_task.ci_channels.add_ci_count_edges_chan(
                self.ci_device+'/'+self.ci_channel,
                initial_count=0,
                count_direction=nidaqmx.constants.CountDirection.COUNT_UP,
                edge=nidaqmx.constants.Edge.RISING
            )
            # Configure the terminal for the signal to count
            ci_channel.ci_count_edges_term = '/'+self.ci_device+'/'+self.ci_terminal
            # Configure the timing
            ci_task.timing.cfg_samp_clk_timing(
                sample_rate,
                source='/'+self.clock_device+'/di/SampleClock',
                active_edge=nidaqmx.constants.Edge.RISING,
                sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
                samps_per_chan=n_samples+readout_delay
            )
            # Arm the start trigger
            ci_task.triggers.arm_start_trigger.trig_type = nidaqmx.constants.TriggerType.DIGITAL_EDGE
            ci_task.triggers.arm_start_trigger.dig_edge_edge = nidaqmx.constants.Edge.RISING
            ci_task.triggers.arm_start_trigger.dig_edge_src = '/'+self.clock_device+'/di/SampleClock'
            # Set the counter buffer size
            ci_task.in_stream.input_buf_size = n_samples+readout_delay

            # Write the data to the AO channel
            ao_task.write(data)

            # Prepare the counter reader for the ci_task
            reader = nidaqmx.stream_readers.CounterReader(ci_task.in_stream)

            # Start the AO task, will wait until the start of the clock task to begin
            ao_task.start()
            # Start the CI task, will wait until the start of the clock task to begin
            ci_task.start()
            # Start the clock task
            clock_task.start()

            # Wait until done
            ao_task.wait_until_done(timeout=n_samples*sample_rate + 1) # 1 second buffer

            # Get the data via the I/O stream
            data_buffer = np.zeros(n_samples+readout_delay,dtype=np.uint32)
            reader.read_many_sample_uint32(
                data_buffer,
                number_of_samples_per_channel=n_samples+readout_delay
            )
            self.ci_data = data_buffer[readout_delay:]

            # Stop the tasks
            clock_task.stop()
            ci_task.stop()
            ao_task.stop()


    def set_voltage(
                self,
                voltage,
        ):
            # Verify the desired voltage is allowed
            self._validate_values(voltage)
            # Create a task on the voltage output, write the desired voltage
            with nidaqmx.Task() as ao_task:
                ao_task.ao_channels.add_ao_voltage_chan(self.ao_device+'/'+self.ao_channel)
                ao_task.write(voltage)


    def _validate_values(
            self,
            data,
    ):
        try:
            voltage = np.array(data)
        except:
            raise TypeError(f'value {data} is not a valid type.')
        if np.any(data < self.ao_min_voltage):
            raise ValueError(f'value {data} is less than {self.ao_min_voltage: .3f}.')
        if np.any(data > self.ao_max_voltage):
            raise ValueError(f'value {data} is greater than {self.ao_max_voltage: .3f}.')


