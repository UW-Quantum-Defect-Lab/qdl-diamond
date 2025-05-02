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
        '''
        Initializes the sequencer.

        Parameters
        ----------
        inputs: dict[str,NidaqSequencerInput]
            Dictionary of `NidaqSequencerInput` instances representing the different input sources
            corresponding to the sequence. The keys of the dictionary should be "user-facing" names
            for the different input sources, e.g. "ai_photodiode", "ci_spcm", etc. The corresponding
            value in the dictionary should be an instance of a `NidaqSequencerInput` child class
            which corresponds to the type of hardware it references. 
        outputs: dict[str,NidaqSequencerOutput]
            Dictionary of `NidaqSequencerOutput` instances representing the different output sources
            corresponding to the sequence. The keys of the dictionary should be "user-facing" names
            for the different output sources, e.g. "ao_laser", "di_trigger", etc. The corresponding
            value in the dictionary should be an instance of a `NidaqSequencerOutput` child class
            which corresponds to the type of hardware it references. 
        clock_device: str
            The name of the DAQ device to assigned the clock task used by the sequencer to 
            coordinate the I/O datastreams.
        clock_channel: str
        The name of the DAQ channel to assigned the clock task used by the sequencer to 
            coordinate the I/O datastreams.
        '''
        # Save the I/O source dictionaries and the clock settings
        self.inputs = inputs
        self.outputs = outputs
        self.clock_device = clock_device
        self.clock_channel = clock_channel
        # Allocate space for sequence metadata
        self.clock_rate = None
        self.soft_start = None
        self.timeout = None

    def run_sequence(
            self,
            data: dict[str,np.ndarray],
            clock_rate: float,
            soft_start: bool = True,
            timeout: float = 300.0
    ):
        '''
        Runs a single sequence writing `data` to the output datastreams and collecing the specified
        number of samples on the input datastreams.

        The data is validated and the output hardware is prepared for the sequence. Then the clock
        task and input/output tasks are configured. The sequence is launched when the clock task
        starts triggering the start of the other tasks. Once all associated I/O tasks have been
        completed, any input data is saved to the associated input instances and the tasks are 
        stopped and closed. At this point, data can be extracted either by directly reading the 
        individual input/output instances, or via the `NidaqSequencer.get_data()` method.

        Parameters
        ----------
        data: dict[str,np.ndarray]
            Dictionary of data vectors with keys corresponding to the particular output sources in
            self.Outputs. The data vectors need not be of equal length.
        clock_rate: float
            Clock rate to use for the sequence.
        soft_start: bool = True
            If `True`, initializes each of the output sources to the first value in their
            corresponding data vector in the `data` dictionary before starting the sequence. This is
            useful if the data vectors do not start and end at the same value.
        timeout: float = 300.0
            The maximum time in seconds that the sequencer will wait for the sequence to finish. If
            you are running experiments involving long sequences then `timeout` should be set longer
            than the expected execution time.
        '''
        # Save the metadata
        self.clock_rate = clock_rate
        self.soft_start = soft_start
        self.timeout = timeout

        # First validate the data
        for name in data:
            self.outputs[name]._validate_data(data[name])

        # Perform a soft start if requested
        if soft_start:
            # Iterate through the output sources and set to the initial data value
            for name in data:
                self.outputs[name].set(data[name][0])

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

    def get_data(
            self,
            names: list[str] = None,
            inputs: bool = True,
            outputs: bool = True
    ) -> dict[str,np.ndarray]:
        '''
        Returns the data currently stored in the input/output sources.
        '''
        # Output dictionary to write results to
        output_dict = {}

        # If specific names are provided, return their data only
        if names is not None:
            # Iterate through the names
            for name in names:
                try:
                    # Look in the inputs dictionary
                    output_dict[name] = self.inputs[name].data
                except KeyError:
                    # If not in the inputs dictionary look in the output dictionary
                    output_dict[name] = self.outputs[name].data
                except:
                    raise KeyError(f'Provided source name {name} does not exist.')
            # Return the output dictionary
            return output_dict
        
        # Return the inputs
        if inputs is True:
            for name in self.inputs:
                output_dict[name] = self.inputs[name].data
        # Return the outputs
        if outputs is True:
            for name in self.outputs:
                output_dict[name] = self.outputs[name].data

        # Return the output dictionary
        return output_dict







