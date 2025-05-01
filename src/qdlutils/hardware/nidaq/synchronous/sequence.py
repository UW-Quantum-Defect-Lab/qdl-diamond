import logging
import numpy as np
import nidaqmx

logger = logging.getLogger(__name__)


class Sequence:

    '''
    This is the template for a generic Sequence wherein various ports on the DAQ are operated
    synchronously. The primary requirement is that there exists a `run_sequence()` method which
    actually performs the sequence. Internal logic of the sequence, types of NIDAQ connections, and
    the storage of data/metadata is left up to the author.

    -   General examples are provided in the files `sequence_ao_ai.py`, `sequence_ao_ci.py` and
        `sequence_ao_ai_ci.py`.

    -   It is recommended to name new files according to the types of I/O that are included. For
        example, to if a new sequence including AO, DO, CI, and DI is required name the file
        `sequence_ao_di_ci_di.py`, labeling the outputs first, then the inputs, each in alphabetical
        order.

    -   Within a given file individual Sequence child classes can be written utilizing different
        types of channels. For example we have in `sequence_ao_ai.py` the class
        `SequenceAOVoltageAIVoltage` which utlizes voltage channels on the AO/AI tasks. However,
        you may also want to perform experiments with AO current, etc. These classes can be included
        in the same file.
    '''

    def __init__(
            self
    ):
        pass


    def run_sequence(
            self,
            data: np.ndarray,
            sample_rate: float,
            soft_start: bool = True,
            readout_delay: int = 0
    ):
        pass