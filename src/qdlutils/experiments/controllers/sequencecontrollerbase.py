import logging
import numpy as np

from qdlutils.hardware.nidaq.synchronous.nidaqsequencer import NidaqSequencer
from qdlutils.hardware.nidaq.synchronous.nidaqsequencerinputgroup import NidaqSequencerInputGroup
from qdlutils.hardware.nidaq.synchronous.nidaqsequenceroutputgroup import NidaqSequencerOutputGroup

from typing import Union, Any, Callable

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class SequenceControllerBase:

    '''
    This is the base class for controlling experiments involving repeated sequences of data I/O.
    This provides one layer of abstraction from explicitly working with the `NidaqSequencer`,
    enabling one to configure the sequence with a single function call and then run an arbitrary
    number of sequences using those settings. It also provides some basic protection from repeated
    requests while the hardware is occupied.

    This class can be used as a base for any experiment involving time-correlated input/output 
    sequences that are repeated many times in succession. For example, it is utilized for PLE in the
    new version of `qdlple` (as of `qdlutils v1.1.0`).

    Attributes
    ----------

    Methods
    -------

    '''

    def __init__(
            self,
            inputs: dict[str,NidaqSequencerInputGroup],
            outputs: dict[str,NidaqSequencerOutputGroup],
            clock_device: str = 'Dev1',
            clock_channel: str = 'port0',
    ):
        '''
        This method initializes the SequenceController class, creates the sequencer that manages 
        individual or repeated sequences, and sets the template for the class attributes.

        Child classes for specific types of experiments should utilze additional arguments in the
        `__init__()` function to specify the source ids of the various hardware elements relevant to
        the experiment. This enables the controller to reference particular hardware without 
        explicitly using the ids (which are arbitrarily chosen by the user). For example if an
        experiment utilzed a scanning laser, then one could create an argument `scan_laser_id` and
        structure the child class `__init__()` as:

        ```
            class LaserScanController(ScanControllerBase):
            
                def __init__(
                    self,
                    inputs: dict[str,NidaqSequencerInput],
                    outputs: dict[str,NidaqSequencerOutput],
                    scan_laser_id: str,
                    clock_device: str = 'Dev1',
                    clock_channel: str = 'port0',
                ):
                    super().__init__(
                        inputs = inputs,
                        outputs = outputs,
                        clock_device = clock_device,
                        clock_channel = clock_channel,
                    )
                    self.scan_laser_id = scan_laser_id
        ```

        Parameters
        ----------
        inputs: dict[str,NidaqSequencerInput]
            Dictionary of input sources with the key being the id and the value being the
            `NidaqSequencerInput` instance.
        outputs: dict[str,NidaqSequencerOutput]
            Dictionary of output sources with the key being the id and the value being the
            `NidaqSequencerOutput` instance.
        clock_device: str = 'Dev1'
            Name of the DAQ device to write the clock on.
        clock_channel: str = 'port0'
            Name of the DAQ channel to write the clock on.
        '''
        # Save the settings
        self.inputs = inputs
        self.outputs = outputs
        self.clock_device = clock_device
        self.clock_channel  = clock_channel

        # Instantiate the sequencer
        self.sequencer = NidaqSequencer(
            inputs = inputs,
            outputs = outputs,
            clock_device = clock_device,
            clock_channel = clock_channel
        )

        # Other attributes to be utilized later
        self.sequence_settings = None
        self.clock_rate = None
        self.output_data = None
        self.input_samples = None
        self.readout_delays = None
        self.soft_start = None
        self.timeout = None

        # Control attributes
        self.busy = False       # True if currently executing an action
        self.stop = False       # Set to `True` externally if controller should stop

    def configure_sequence(
            self,
            **sequence_setting_kwargs
    ):
        '''
        This method calculates the relevant values for the input/output data streams given the
        parameters for the sequence. The parameters naturally vary depending on how one intends to
        structure the experiment. This method should set the following attributes:

            -   `clock_rate: float`
                    The clock rate to perform the sequence at
            -   `output_data`: dict[str, np.ndarray]
                    A dictionary with keys identifying output sources and values corresponding to
                    the data that should be written by that source.
            -   `input_samples`: dict[str, int]
                    A dictionary with keys identifying input sources and values corresponding to the
                    number of samples that should be recorded by that source
            -   `readout_delays`: dict[str, int]
                    A dictionary with keys identifying input sources and values corresponding to the
                    number of clock cycles to delay the start of input collection
            -   `soft_start`: dict[str, int]
                    A dictionary with keys identifying output sources and values corresponding to
                    `True` if the output source should be set to the start value of its output data
                    prior to running a sequence. If `False`, *or if the source id is not supplied*, 
                    then the value of the output source immediately before the sequence will remain 
                    whatever it was set to last.
            -   `timeout`: float
                    The time in seconds the seqencer waits for a sequence to finish before aborting 
                    the attempt. Should be set to be at least as long as the projected time.

        Parameters
        ----------
        **sequence_setting_kwargs
            Keyword arguments describing the parameters for the sequence
        '''

        # The setting kwargs should be saved as a dict for metadata.
        self.sequence_settings = sequence_setting_kwargs

    def _run_sequence(
            self,
            process_method: Callable = None,
            process_kwargs: dict = {}
    ) -> Union[dict[str,np.ndarray], Any]:
        '''
        Runs a single sequence utilizing the currently stored sequencer and associated class 
        attributes. Class method `configure_sequence()` should be executed before this.

        This method is not intended to be called externally in most cases as it does not support any
        hardware protection. For most purposes it is sufficient to call `run_n_sequences(n=1)` 
        instead.

        Attributes
        ----------
        process_method: Callable = None
            A function which processes the data. The first argument must accept the source data in
            the form of `dict[str,np.ndarray]`. There are no restrictions on the return type of this
            method.
        **process_kwargs
            Keyword arguments for the `process_method()` function.

        Returns
        -------
        data
            Default behavior is to simply return the entire dataset as readout from the sequencer as
            returned by the `NidaqSequencer.get_data()` method, i.e. as `dict[str,np.ndarray]` where
            the key-value pair corresponds to the source id and data respectively. If the optional
            argument `process_method` is provided, the return type will match the return type of the
            `process_method` function.
        '''
        # Run the sequence
        self.sequencer.run_sequence(
            clock_rate=self.clock_rate,
            output_data=self.output_data,
            input_samples=self.input_samples,
            readout_delays=self.readout_delays,
            soft_start=self.soft_start,
            timeout=self.timeout
        )
        # Return the data dictionary if no process method is provided
        if process_method is None:
            return self.sequencer.get_data()
        else:
            # Otherwise return the processed data
            return process_method(self.sequencer.get_data(), **process_kwargs)
    
    def run_n_sequences(
            self,
            n: int,
            process_method: Callable = None,
            process_kwargs: dict = {}
    ):
        '''
        This method runs `n` sequences with the current configureation, handling interruptions for 
        stopping. The data is returned via `yield` after each sequence.

        Parameters
        ----------
        n: int
            The number of sequence to perform consequtively.
        process_method: Callable = None
            A function which processes the data. The first argument must accept the source data in
            the form of `dict[str,np.ndarray]`. There are no restrictions on the return type of this
            method. For convenience, the class method `process_data()` can be modified for this;
            otherwise, an external function can be supplied.
        **process_kwargs
            Keyword arguments for the `process_method()` function.

        Yields
        ------
        data
            Default behavior is to simply return the entire dataset as readout from the sequencer as
            returned by the `NidaqSequencer.get_data()` method, i.e. as `dict[str,np.ndarray]` where
            the key-value pair corresponds to the source id and data respectively. If the optional
            argument `process_method` is provided, the return type will match the return type of the
            `process_method` function.

        Notes
        -----
        This method is implemented as a generator function which yields the data and checks for user
        interruptions after each sequence is completed. The start of a new sequence also requires
        writing tasks to the DAQ and preparing the hardware. As a consequence, a small temporal 
        overhead is incurred between each sequence. Thus, this method is not necessarily suitable 
        in cases where: (1) the time between subsequent sequences is important, and (2) the 
        individual sequences are short and numerous such that the overhead incurred constitutes a
        large fraction of the total time of a cycle.

        Nevertheless, this method (and class) can still be utilized effectively in such cases.
        Instead of programming a sequence as a "single shot" of the experiment, one can instead
        define the I/O datastreams in `configure_sequence()` to represent some larger number of 
        repeated "shots" of the experiment which, when written to the DAQ, will be performed with
        no computational overhead. Some post-processing of the data will be required and can be
        managed by supplying the `process_method`.
        '''

        # Block action if busy
        if self.busy:
            raise RuntimeError('Application controller is currently in use.')

        # Reserve the controller
        self.busy=True

        for i in range(n):
            # Run a single sequence and yield the data
            yield self._run_sequence(process_method=process_method,process_kwargs=process_kwargs)
            # Check if the software has requested to stop; exit if true.
            if self.stop:
                logger.info('Stopping sequence.')
                break

        # Release controller
        self.busy=False
        self.stop=False
        logger.info('Completed sequence.')


    def set_output(
            self,
            output_id: str,
            setpoint: Union[float, int, bool]
    ) -> None:
        '''
        Sets the output of the controller specified by `output_id` to the `setpoint`.
        '''
        # Block action if busy
        if self.busy:
            raise RuntimeError('Controller is currently in use.')
        # Reserve the controller
        self.busy=True
        # Attempt to set the value of the specified output to the set point
        try:
            self.sequencer.set_output(output_name = output_id, setpoint=setpoint)
        except Exception as e:
            raise e
        # Release the controller
        self.busy=False

    def process_data(
            self,
            data: dict[str,np.ndarray],
            **kwargs
    ) -> Any:
        '''
        Method to process the data obtained from a single sequence run.
        '''
        pass
