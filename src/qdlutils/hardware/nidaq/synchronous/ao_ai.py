import time
import logging

import numpy as np

import nidaqmx


from qdlutils.hardware.nidaq.counters.nidaqedgecounterinterface import NidaqEdgeCounterInterface

logger = logging.getLogger(__name__)


class AnalogOutputAnalogInput:
    '''
    This class implements synchronus analog voltage output (AO) and analog voltage input (AI) tasks mediated by an 
    internal clock.
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
            sample_rate: float
    ):
        
        n_samples = len(data)

        # Create the tasks
        with nidaqmx.Task() as ao_task, nidaqmx.Task() as ai_task:

            # Add the AO voltage channel to the AO task
            ao_task.ao_channels.add_ao_voltage_chan(self.ao_device + '/' + self.ao_channel)
            # Configure the timing on the AO task
            ao_task.timing.cfg_samp_clk_timing(
                sample_rate, 
                sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS
            )

            # Add the AI voltage channel to the AI task
            ai_task.ai_channels.add_ai_voltage_chan(self.ai_device + '/' + self.ai_channel)
            # Configure the timing on the AI task to operate for as many samples as there are data points in the
            # provided data vector
            ai_task.timing.cfg_samp_clk_timing(
                sample_rate, 
                sample_mode=nidaqmx.constants.AcquisitionType.FINITE, 
                samps_per_chan=n_samples
            )
            # Set the start trigger to be the start trigger of the ao_task
            ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(self.ao_device + '/ao/StartTrigger')


            # Start the AI task, runs for `n_samples` after reciving start trigger of the AO task
            ai_task.start()
            # Start the AO task, runs indefinitely until stopped
            ao_task.start()

            # Wait for the AI task to finish
            ai_task.wait_until_done()

            # Get the data
            self.data = ai_task.read(nidaqmx.constants.READ_ALL_AVAILABLE)

            # Stop the AI task
            ai_task.stop()
            # Stop the AO task
            ao_task.stop()
            


            

            


