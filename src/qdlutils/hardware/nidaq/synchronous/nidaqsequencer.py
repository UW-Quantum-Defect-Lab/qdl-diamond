import logging
import numpy as np
import nidaqmx
import nidaqmx.constants

from qdlutils.hardware.nidaq.synchronous.sequence import Sequence
from qdlutils.hardware.nidaq.synchronous.nidaqsequencerinput import NidaqSequencerInput
from qdlutils.hardware.nidaq.synchronous.nidaqsequenceroutput import NidaqSequencerOutput


class NidaqSequencer(Sequence):

    '''
    This class implements a generic, programmable synchronous I/O sequencer for NIDAQ controlled
    instruments.

    The general goal is to enable the user to program arbitrary coordinated streams of input and 
    output tasks on the DAQ, synched by a shared virtual clock. This is a powerful tool for 
    performing pulse sequences involving multiple pieces of hardware that need to be coordianted.
    In effect, this is similar to implementing a pulse blaster using a NIDAQ PCIe board.

    To utilize this, one creates two dictionaries of `NidaqSequencerInput` and 
    `NidaqSequencerOutput` objects respectively which each encapsulate specific hardware or signals 
    that one would like to coordinate via the DAQ. These dictionaries are passed to the sequencer
    which can then freely create and execute the corresponding DAQ tasks. In theory, an arbitrary
    number of inputs/outputs may be utilzed at the same time allowing for significant flexibility.
    Of course, one must ensure that the desired tasks are compatible with hardware limiations of the
    specific DAQ board being used.
    
    After intitalization, the user can then run a "sequence" via the `NidaqSequencer.run_sequence()`
    method. A "sequence" in this context refers to a single batch of coordinated input/output 
    datastreams. That is to say, the input tasks will readout the input datastream for however many
    samples they are set to, and the output tasks will write all of the data they are provided to
    write. In this sense, a sequence is a single shot of the experiment which may be repeated many
    times --- e.g. one scan of a PLE experiment or one pump-probe cycle in ODMR. Both the readout 
    datastreams of the `NidaqSequencerInput` and the write values of the`NidaqSequencerOutput` for 
    the most recent sequence are saved in their respective instances.
    '''

    def __init__(
            self,
            inputs: dict[str,NidaqSequencerInput],
            outputs: dict[str,NidaqSequencerOutput],
            clock_device: str = 'Dev1',
            clock_channel: str = 'port0'
    ) -> None:
        
        self.inputs = inputs
        self.outputs = outputs
        self.clock_device = clock_device
        self.clock_channel = clock_channel

        self.clock_rate = None

    def run_sequence(
            self,
            data: dict[str,np.ndarray],
            clock_rate: float,
            soft_start: bool = True,
            timeout: float = 300.0
    ):
        
        # Do preparation stuff here

        # Create the clock task
        with nidaqmx.Task() as clock_task:

            # Initialize virtual DI clock task on an internal channel
            clock_task.di_channels.add_di_chan(self.clock_device+'/'+self.clock_channel)
            clock_task.timing.cfg_samp_clk_timing(
                clock_rate,
                sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS
            )
            # Commit the clock task to hardware
            clock_task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)


            # Initialize and start the input tasks
            for name in self.inputs:
                self.inputs[name].build(sample_rate = clock_rate, clock_device = self.clock_device)
                self.inputs[name].task.start()

            # Initialize and start the output tasks
            for name in self.outputs:
                self.outputs[name].build(sample_rate = clock_rate, clock_device = self.clock_device)
                self.outputs[name].write(data[name])
                self.outputs[name].task.start()


            # Start the clock task and begin data I/O
            clock_task.start()


            # Wait until done
            for name in self.inputs:
                self.inputs[name].task.wait_until_done(timeout=timeout)
            for name in self.outputs:
                self.outputs[name].task.wait_until_done(timeout=timeout)

            # Read the data from the input sources
            for name in self.inputs:
                self.inputs[name].readout()


            # Close out the tasks
            for name in self.inputs:
                self.inputs[name].close()
            for name in self.outputs:
                self.outputs[name].close()
            







