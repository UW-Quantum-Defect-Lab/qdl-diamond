import logging
import numpy as np
import nidaqmx

logger = logging.getLogger(__name__)


class AnalogOutputAnalogInput:
    '''
    This class implements synchronus analog voltage output (AO) and analog voltage input (AI) tasks 
    mediated by an internal clock.
    '''

    def __init__(
            self, 
            ao_device: str = 'Dev1',
            ao_channel: str = 'ao0',
            ai_device: str = 'Dev1',
            ai_channel: str = 'ai0',
            ao_min_voltage: float = -5.0,
            ao_max_voltage: float = 5.0,
            ai_min_voltage: float = -5.0,
            ai_max_voltage: float = 5.0
    ) -> None:
        
        self.ao_device = ao_device
        self.ao_channel = ao_channel
        self.ai_device = ai_device
        self.ai_channel = ai_channel
        self.ao_min_voltage = ao_min_voltage
        self.ao_max_voltage = ao_max_voltage
        self.ai_min_voltage = ai_min_voltage
        self.ai_max_voltage = ai_max_voltage


        # Buffer to store data for last executed sequence
        self.data = None


    def run_sequence(
            self,
            data: np.ndarray,
            sample_rate: float,
            soft_start: bool = True
    ):
        # Verify the desired voltage is allowed
        self._validate_values(data)

        # Get the number of samples
        n_samples = len(data)

        # If `soft_start` is enabled, set the initial voltage match the first datum in data
        if soft_start:
            self.set_voltage(data[0])

        # Create the tasks
        with nidaqmx.Task() as ao_task, nidaqmx.Task() as ai_task:

            # Add the AI voltage channel to the AO task
            ai_task.ai_channels.add_ai_voltage_chan(self.ai_device + '/' + self.ai_channel)
            # Configure the timing on the AI task
            # Set the sample mode to continuous so that it runs continually until the ao_task
            # completes and stops. This is useful if one wants to run multiple readouts on the same
            # ai_task without rebooting.
            ai_task.timing.cfg_samp_clk_timing(
                sample_rate, 
                sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS
            )

            # Add the AO voltage channel to the AO task
            ao_task.ao_channels.add_ao_voltage_chan(self.ao_device+'/'+self.ao_channel)
            # Configure the timing on the AO task to operate for as many samples as there are data
            # points in the provided data vector. Running on the finite sample mode ensures that
            # only the voltage samples provided in the data vector are written.
            ao_task.timing.cfg_samp_clk_timing(
                sample_rate, 
                sample_mode=nidaqmx.constants.AcquisitionType.FINITE, 
                samps_per_chan=n_samples
            )
            # Set the start trigger to be the start trigger of the ai_task
            ao_task.triggers.start_trigger.cfg_dig_edge_start_trig('/'+self.ai_device+'/ai/StartTrigger')

            # Write the data to the AO channel
            ao_task.write(data)

            # Start the AO task, runs for `n_samples` after reciving start trigger of the AO task
            # but does not start until the start trigger from the AI task.
            ao_task.start()
            # Start the AI task, runs indefinitely until stopped by software
            ai_task.start()
            
            # Wait for the AI task to finish
            ao_task.wait_until_done(timeout=n_samples*sample_rate + 3) # 3 second buffer
            
            # Get the data by reading the first `n_samples`.
            self.data = ai_task.read(number_of_samples_per_channel=n_samples)

            # Stop the AI task
            ai_task.stop()
            # Stop the AO task
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
