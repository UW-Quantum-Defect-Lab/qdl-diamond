import logging
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import nidaqmx
import nidaqmx.constants

# Because we are on Python 3.9 type union operator `|` is not yet implemented
from typing import Union

from qdlutils.hardware.nidaq.synchronous.sequence import Sequence
from qdlutils.hardware.nidaq.synchronous.nidaqsequencerinputgroup import NidaqSequencerInputGroup
from qdlutils.hardware.nidaq.synchronous.nidaqsequenceroutputgroup import NidaqSequencerOutputGroup

class NidaqSequencer(Sequence):

    def __init__(
            self,
            inputs: dict[str,NidaqSequencerInputGroup],
            outputs: dict[str,NidaqSequencerOutputGroup],
            clock_device: str,
            clock_channel: str,
            clock_terminal: str
    ):
        '''
        Initializes the sequencer.
        '''
        self.inputs = inputs
        self.outputs = outputs
        self.clock_device = clock_device
        self.clock_channel = clock_channel
        self.clock_terminal = clock_terminal

        # Additional parameters to be utilized later
        self.clock_rate = None
        self.soft_start = None
        self.timeout = None

        # Get the source names for each input/output. This creates a dictionary with each key, value
        # pair giving the name of the `NidaqSequencerInput/OuputGroup` instances supplied and their
        # corresponding source names as a list.
        self.input_source_names = {
            name: input_group.source_names for name, input_group in inputs.items()
        }
        self.output_source_names = {
            name: output_group.source_names for name, output_group in outputs.items()
        }
        # We also want to invert the structure to determine which task a given input is associated
        # with. Thus we create a dictionary with inverted structure wherein each key is the name of
        # a given source and the value is the name of the corresponding 
        # `NidaqSequencerInput/OutputGroup`
        self.input_source_group = {}
        for group, sources in self.input_source_names.items():
            for source in sources:
                # Names for the sources should be unique to avoid ambiguity in data reading/writing.
                # If a source with a given name already exists then throw an error
                if source in self.input_source_group:
                    raise ValueError(f'The input source name {source} is redundantly defined.')
                self.input_source_group[source] = group
        self.output_source_group = {}
        for group, sources in self.output_source_names.items():
            for source in sources:
                # Names for the sources should be unique to avoid ambiguity in data reading/writing.
                # If a source with a given name already exists then throw an error
                if source in self.output_source_group:
                    raise ValueError(f'The output source name {source} is redundantly defined.')
                self.output_source_group[source] = group


    def run_sequence(
            self,
            clock_rate: float,
            output_data: dict[str,np.ndarray],
            input_samples: dict[str,int],
            readout_delays: dict[str,int] = {},
            soft_start: dict[str, bool] = {},
            timeout: float = 300.0
    ) -> None:
        '''
        Parameters
        ----------
        clock_rate: float
            Clock rate to perform the sequence at. Samples and data are written on each cycle.
        output_data: dict[str,np.ndarray]
            A dictionary indicating the data to write during the sequence. The keys are the names of
            individual output sources as defined in each `NidaqSequencerOutputGroup` instance. The values
            are the associated `numpy` arrays of data to write. The data must be one-dimensional and
            have consistent shape within any group of sources associated to the same 
            `NidaqSequencerOutputGroup` instance. This is required as interpolation of the data to output
            is ambiguous. 
        input_samples: dict[str,int]
            A dictionary indicating the number of samples to read for any given input source. The
            keys should be the names associated to specific input channels and the values should be
            the number of samples.
        readout_delays: dict[str,int] = {}
            A dictionary indicating the number of samples to delay readout for any given input 
            source. The keys should be the names associated to specific input channels and the 
            values should be the number of samples. If a key is not provided the readout delay is 
            assumed to be zero.
        soft_start: dict[str, bool] = {}
            A dictionary indicating if the given outputs should be set to their initial values
            before executing the sequence. The keys should match individual output sources as 
            defiend in their corresponding `NidaqSequencerOutpuGroup` instances. The values are boolean
            indicating if the corresponding output should be set. If not included the default is to
            not perform a soft start (i.e. `False`).
        timeout: float = 300.0
            Timeout for the sequence to complete running. Should be set longer than the expected
            time, e.g. `n_samples`/`clock_rate`.
        '''
        # Verify the parameters are valid and get the readout delays if not provided.
        readout_delays = self._parse_sequence_params(
            output_data=output_data,
            input_samples=input_samples,
            readout_delays=readout_delays
        )

        # Check if any outputs should have a soft start and update if so
        for name in soft_start:
            # Perform a soft start if requested
            if name in self.output_source_group and soft_start[name]:
                # Set to the value at the start of the data
                self.set_output(output_name=name,setpoint=output_data[name][0])

        # Create the clock task
        with nidaqmx.Task() as clock_task:

            # Initialize virtual DI clock task on an internal channel
            # In principle one could instead create a DO channel and output the clock to one of the
            # DO pins on the DAQ board. This would enable synching of other hardware.
            clock_task.di_channels.add_di_chan(self.clock_device+'/'+self.clock_channel)
            clock_task.timing.cfg_samp_clk_timing(
                clock_rate,
                sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS
            )
            # Commit the clock task to hardware
            clock_task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)

            # Initialize and start the input tasks
            for name in self.inputs:
                # Build the task and configure the timings
                self.inputs[name].build(
                    n_samples = input_samples,
                    clock_device = self.clock_device,
                    sample_rate = clock_rate,
                    readout_delays = readout_delays
                )
                # Start the task
                # It will not actually begin until after the clock task starts
                self.inputs[name].task.start()
            # Initialize and start the output tasks
            for name in self.outputs:
                # Build the task and configure the timings
                self.outputs[name].build(
                    data = output_data,
                    clock_device = self.clock_device,
                    sample_rate = clock_rate
                )
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
            outputs: bool = True,
    ) -> dict[str, np.ndarray]:
        '''
        Returns the data currently stored in the input/output sources.

        Parameters
        ----------
        names: list[str]
            List of names of input/output sources to get the data from. By default `None`; if a list 
            is provided then the data of only those sources is returned.
        inputs: bool = True,
            If `True` and `names` is `None`, output will contain all input source data.
        outputs: bool = True
            If `True` and `names` is `None`, output will contain all output source data.

        Returns
        -------
        data : dict[str, np.ndarray]
            A dictionary whose keys are the names of the input/output sources with value 
            corresponding to the data obtained in the last completed sequence. The key-value pairs 
            included in the dictionary include only those specified by the arguments to this method.
        '''
        # Output dictionary to write results to
        data = {}

        # If specific names are provided, return their data only
        if names is not None:
            # Iterate through the names
            for name in names:
                try:
                    # Look in the inputs dictionary
                    data_dict = self.inputs[self.input_source_group[name]].data
                except KeyError:
                    # If not in the inputs dictionary look in the output dictionary
                    data_dict = self.outputs[self.output_source_group[name]].data
                except:
                    raise KeyError(f'Provided source name {name} does not exist.')
                # Store the retrieved data (update in place)
                data |= data_dict

            # Return the output dictionary
            return data
        
        # If specific names are not provided get all inputs and/or outputs.
        # Get the input source data
        if inputs is True:
            for group in self.input_source_names:
                data |= self.inputs[group].data

        # Get the output source data
        if outputs is True:
           for group in self.output_source_names:
                data |= self.outputs[group].data

        # Return the output dictionary
        return data

    def check_sequence(
            self,
            clock_rate: float,
            output_data: dict[str,np.ndarray],
            input_samples: dict[str,int],
            readout_delays: dict[str,int] = {},
            input_sources_to_plot: list[str] = None,
            output_sources_to_plot: list[str] = None,
    ) -> matplotlib.figure.Figure:
        '''
        Returns a matplotlib figure illustrating the source datastreams.
        '''

        # Verify the parameters are valid and get the readout delays if not provided.
        readout_delays = self._parse_sequence_params(
            output_data=output_data,
            input_samples=input_samples,
            readout_delays=readout_delays
        )

        # If no specific sources are requested plot them all
        if input_sources_to_plot is None:
            input_sources_to_plot = list(self.input_source_group)
        if output_sources_to_plot is None:
            output_sources_to_plot = list(self.output_source_group)

        # Create the figure
        total_num_sources = len(input_sources_to_plot) + len(output_sources_to_plot)

        fig, ax = plt.subplots(
            nrows=total_num_sources,
            ncols=1,
            sharex=True,
            gridspec_kw={'hspace':0, 'left':0.25, 'right':.95}
        )
        idx = 0
        for name in output_sources_to_plot:
            ax[idx].plot(
                np.arange(len(output_data[name])), 
                output_data[name],
                'o-',
                markersize=2
            )
            ax[idx].set_ylabel(name, rotation=0, ha='right', labelpad=10)
            idx += 1
        for name in input_sources_to_plot:
            input_window = np.concat(
                [np.zeros(readout_delays[name]), np.ones(input_samples[name])]
            )
            ax[idx].plot(
                np.arange(len(input_window)), 
                input_window,
                'o-',
                markersize=2
            )
            ax[idx].fill_between(
                np.arange(len(input_window)), 
                input_window,
                color='C0',
                alpha=0.5
            )
            ax[idx].set_ylabel(name, rotation=0, ha='right', labelpad=10)
            idx += 1

        # Label the x axis
        ax[idx-1].set_xlabel('sample number')

        # Set the second x axis
        def time_to_sample(x):
            return x * clock_rate
        def sample_to_time(x):
            return x / clock_rate
        time_axis = ax[0].secondary_xaxis('top', functions=(sample_to_time, time_to_sample))
        time_axis.set_xlabel('time (s)')

        return fig

    def set_output(
            self,
            output_name: str,
            setpoint: Union[float, int, bool]
    ):
        '''
        Sets the value of the requested output source to the specified setpoint.
        '''
        # Set the value
        self.outputs[self.output_source_group[output_name]].set(output_name=output_name,setpoint=setpoint)

    def validate_output_data(
            self,
            output_name: str,
            data: Union[float, int, bool, np.ndarray]
    ):
        '''
        Validates the provided data for output on the given output source
        '''
        self.outputs[self.output_source_group[output_name]]._validate_data(output_name=output_name,data=data)

    def _parse_sequence_params(
            self,
            output_data: dict[str,np.ndarray],
            input_samples: dict[str,int],
            readout_delays: dict[str,int]
    ) -> dict[str,int]:
        '''
        Verifies that the sequence parameters are valid, returns modified input sample and readout.

        Returns
        -------
        readout_delays: dict[str,int]
            The `readout_delays` dictionary with new items for each input source not provided.

        Notes
        -----
        The output source data within a group is required to be the same as the write datastream
        within a given task must have the same shape for all channels in that task. This is because
        Interpolation of the write data beyond what is explicitly provided is ambiguous (e.g. set to
        "zero", hold the last written value, etc.). In fact, the behavior of the physical channel on
        the DAQ itself is often ambiguous in such instances as well, and so all output data should
        be of the same size. However, we do not enforce that here as one may want to have groups of
        tasks with different sample rates, or have some well-defined method of interpolating data.
        '''
        # Verify that the output data for sources within each output group is valid
        for group, source_names in self.output_source_names.items():

            # Check if the data is defined and if it is valid for the output soruce
            for src in source_names:
                if src not in output_data:
                    raise ValueError(f'Output data for source {src} was not defined.')
                else:
                    try:
                        self.outputs[group]._validate_data(output_name=src,data=output_data[src])
                    except (TypeError, ValueError) as e:
                        raise ValueError(f'Output data for source {src} is invalid: {e}')

            # Get the shapes of the data
            shapes = [output_data[src].shape for src in source_names]
            # Check if identical by converting to set
            if len(set(shapes)) > 1:
                raise ValueError(f'Length of data arrays for group {group}, {shapes}, do not match.')
            # Make sure the shapes are one dimensional
            if len(shapes[0]) > 1:
                raise ValueError(f'Data arrays for group {group} have shape {shapes[0]}, but must be one-dimensional.')
            

        # Append readout delays of zero for any sources not explicitly defined.
        for group, source_names in self.input_source_names.items():
            for src in source_names:

                # Check that the input samples are valid and completely defined
                if src not in input_samples:
                    raise ValueError(f'The number of input samples for source {src} is undefined.')
                elif input_samples[src] < 0:
                    raise ValueError(f'The number of input samples for source {src} is invalid.')

                # Fix the readout delays
                if src not in readout_delays:
                    readout_delays[src] = 0
                elif readout_delays[src] < 0:
                    raise ValueError(f'Readout delay for source {src}, {readout_delays[src]}, cannot be negative.')

        return readout_delays
                
