import logging
import os
import numpy as np
import matplotlib.pyplot as plt
import time
import h5py
import nidaqmx

from qdlutils.hardware.nidaq.synchronous.nidaqsequencerinputgroup import (
    NidaqSequencerCIEdgeGroup,
    NidaqSequencerCIEdgeRateGroup
)
from qdlutils.hardware.nidaq.synchronous.nidaqsequenceroutputgroup import (
    NidaqSequencerDO32LineGroup,
    NidaqSequencerAOVoltageGroup
)
from qdlutils.experiments.controllers.sequencecontrollerbase import SequenceControllerBase
from qdlutils.hardware.wavemeters.wavemeters import WavemeterController

from IPython import display
from typing import Union, Any, Callable


from qdlutils.experiments.laser_pulse_sequencing.repump_probe_sequence_base import (
    RepumpProbeSequenceBase
)


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class StateMonitoringExperiment(RepumpProbeSequenceBase):

    '''
    This class implements a simple state monitoring experimental sequence. The experimental protocol
    is comprised of two lasers "repump" and "probe". The repump is periodically pulsed to pump the
    system into a given state while the probe monitors the state. Graphically:

    ```
        repump    __|=======|___________________________________

        probe     ______________|===========================|___ 

                    |       |   |                           |   |
                    t=0     t1  t2                          t3  t4

        t1      = Repump time
        t2 - t1 = Delay between repump and probe start
        t3 - t2 = Probe time
        t4 - t3 = Delay betwen probe and start of next repetition
    ```

    The repump laser is assumed to be some static off resonant laser with pulse control via a 
    digital output.
    The probe laser is assumed to be tunable with some analog output voltage and have pulse control
    via a digital output. For this implementation the probe laser is assumed to not be actively
    controlled during the course of the sequence and is instead stabilized in between sequence
    executions.
    A wavemeter controller class for managing the probe laser frequency is expected to be
    initialized prior to the start of the experiment.
    Readout via an SPCM counter channel is expected to be performed over the duration of each
    sequence.
    '''

    def __init__(
            self,
            repump_id: str,
            repump_do_config: dict,
            probe_id: str,
            probe_do_config: dict,
            probe_ao_config: dict,
            counter_id: str,
            counter_ci_config: dict,
            wavemeter_controller: WavemeterController,
            clock_device: str = 'Dev1',
            clock_channel: str = 'ctr0',
    ):
        # Just init from the base class
        super().__init__(
            repump_id = repump_id,
            repump_do_config = repump_do_config,
            probe_id = probe_id,
            probe_do_config = probe_do_config,
            probe_ao_config = probe_ao_config,
            counter_id = counter_id,
            counter_ci_config = counter_ci_config,
            wavemeter_controller = wavemeter_controller,
            clock_device = clock_device,
            clock_channel = clock_channel
        )

    def get_sequence_output_data(
            self,
            repump_time: float,
            probe_delay: float,
            probe_time: float,
            end_delay: float,
    ):
        '''
        Accepts keyword arguments defining the pulse sequence to perform and computes the output
        datastreams then saves the sequence settings dictionary as metadata. Must set the parameters
        following parameters in the class instance which describe the single sequence:
        ```
            self.single_sequence_repump_data# Binary vector representing when the repump laser is on
            self.single_sequence_probe_data # Binary vector representing when the probe laser is on
            self.single_sequence_n_samples  # Number of samples
            self.sequence_settings          # A dictionary describing the necessary information to
                                            # recreate the pulse sequence. Saved as metadata.
        ```

        Parameters
        ----------
        repump_time: float
            Repump time for the sequence in seconds.
        probe_delay: float
            Delay between the end of the repump and start of the probe in seconds.
        probe_time: float
            Length of the probe time in seconds.
        end_delay: float
            Delay at after the probe ends before the next repetition begins in seconds.
        '''

        # Get the times associated to the relevant points in the sequence in terms of clock cycles
        idx1 = int(repump_time * self.clock_rate)
        idx2 = idx1 + int(probe_delay * self.clock_rate)
        idx3 = idx2 + int(probe_time * self.clock_rate)
        idx4 = idx3 + int(end_delay * self.clock_rate)       # Number of samples per individual sequence

        self.single_sequence_n_samples = idx4

        # Generate data for a single sequence
        self.single_sequence_time = np.arange(self.single_sequence_n_samples) / self.clock_rate
        self.single_sequence_repump_data = np.zeros(self.single_sequence_n_samples, dtype=np.int32)
        self.single_sequence_repump_data[0:idx1] = 1
        self.single_sequence_probe_data = np.zeros(self.single_sequence_n_samples, dtype=np.int32)
        self.single_sequence_probe_data[idx2:idx3] = 1

        # Save the sequence parameters
        self.sequence_settings = {
            'n_batches': self.n_batches,
            'n_repetitions': self.n_repetitions,
            'repump_time': repump_time,
            'probe_delay': probe_delay,
            'probe_time': probe_time,
            'end_delay': end_delay,
            'clock_rate': self.clock_rate,
            'single_sequence_samples': self.single_sequence_n_samples
        }







