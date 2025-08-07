import logging
import numpy as np
import time

from qdlutils.hardware.nidaq.synchronous.nidaqsequencer import NidaqSequencer
from qdlutils.hardware.nidaq.synchronous.nidaqsequencerinputgroup import NidaqSequencerInputGroup
from qdlutils.hardware.nidaq.synchronous.nidaqsequenceroutputgroup import NidaqSequencerOutputGroup

from qdlutils.hardware.wavemeters.wavemeters import WavemeterController

from qdlutils.experiments.controllers.sequencecontrollerbase import SequenceControllerBase

from typing import Union, Any, Callable
from threading import Thread

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class PLEControllerBase(SequenceControllerBase):

    def __init__(
            self,
            inputs: dict[str,NidaqSequencerInputGroup],
            outputs: dict[str,NidaqSequencerOutputGroup],
            scan_laser_id: str,
            clock_device: str = 'Dev1',
            clock_channel: str = 'port0',
            clock_rate: float = 10000,
            process_instructions: dict = {}
    ):
        super().__init__(
            inputs = inputs,
            outputs = outputs,
            clock_device = clock_device,
            clock_channel = clock_channel,
        )
        self.scan_laser_id = scan_laser_id
        self.clock_rate = clock_rate
        self.process_instructions = process_instructions




class PLEControllerPulsedRepumpContinuous(PLEControllerBase):

    '''
    This class implements the PLE scan controller for PLE experiments with a single pulsed repump at
    the start of each scan. Outputs are limited to the scan laser and the repump laser signals. The
    controller supports an arbitrary number of input sources.
    '''

    def __init__(
            self,
            inputs: dict[str,NidaqSequencerInputGroup],
            outputs: dict[str,NidaqSequencerOutputGroup],
            scan_laser_id: str,
            repump_laser_id: str,
            repump_laser_setpoints: dict = {'on': 1, 'off':0},
            clock_device: str = 'Dev1',
            clock_channel: str = 'port0',
            clock_rate: float = 10000,
            process_instructions: dict = {}
    ):
        super().__init__(
            inputs = inputs,
            outputs = outputs,
            scan_laser_id = scan_laser_id,
            clock_device = clock_device,
            clock_channel = clock_channel,
            clock_rate = clock_rate,
            process_instructions = process_instructions
        )
        self.repump_laser_id = repump_laser_id
        self.repump_laser_setpoints = repump_laser_setpoints

        # Laser scan parameters
        self.min=None
        self.max=None
        self.n_pixels_up=None
        self.n_pixels_down=None
        self.n_subpixels=None
        self.n_subpixels_up=None
        self.n_subpixels_down=None
        self.time_up=None
        self.time_down=None
        self.time_repump=None

        self.time_per_subpixel_up = None
        self.time_per_subpixel_down = None
        self.cycles_per_subpixel_up = None
        self.cycles_per_subpixel_down = None
        self.cycles_per_repump = None

        self.n_samples_repump = None
        self.n_samples_upscan = None
        self.n_samples_downscan = None
        self.n_samples_scan = None
        self.n_samples_total = None

    def configure_sequence(
            self,
            min,
            max,
            n_pixels_up,
            n_pixels_down,
            n_subpixels,
            time_up,
            time_down,
            time_repump,
            **misc_kwargs
    ):
        # Save the scan parameters
        self.min=min
        self.max=max
        self.n_pixels_up=n_pixels_up
        self.n_pixels_down=n_pixels_down
        self.n_subpixels=n_subpixels
        self.n_subpixels_up=n_subpixels*n_pixels_up
        self.n_subpixels_down=n_subpixels*n_pixels_down
        self.time_up=time_up
        self.time_down=time_down
        self.time_repump=time_repump

        self.sequence_settings = {
            'min': self.min,
            'max': self.max,
            'n_pixels_up': self.n_pixels_up,
            'n_pixels_down': self.n_pixels_down,
            'n_subpixels': self.n_subpixels,
            'n_subpixels_up': self.n_subpixels_up,
            'n_subpixels_down': self.n_subpixels_down,
            'time_up': self.time_up,
            'time_down': self.time_down,
            'time_repump': self.time_repump,
            'clock_rate': self.clock_rate,
        }

        # Check if the max > min and both are within the scan laser's range
        if max > min:
            self.outputs[self.scan_laser_id]._validate_data(data=min)
            self.outputs[self.scan_laser_id]._validate_data(data=min)
        else:
            raise ValueError(f'Requested max {max:.3f} is less than min {min:.3f}.')
        # Check if pixel numbers are positive integers
        if type(n_pixels_up) is not int or n_pixels_up < 1:
            raise ValueError(f'Requested # pixels up {n_pixels_up} is invalid (must be at least 1).')
        if type(n_pixels_down) is not int or n_pixels_down < 1:
            raise ValueError(f'Requested # pixels down {n_pixels_down} is invalid (must be at least 1).')
        if type(n_subpixels) is not int or n_subpixels < 1:
            raise ValueError(f'Requested # subpixels {n_subpixels} is invalid (must be at least 1).')
        # Check that up/downscan times are greater than zero.
        if not (time_up > 0):
            raise ValueError(f'Requested upsweep time {time_up}s is invalid (must be > 0).')
        if not (time_down > 0):
            raise ValueError(f'Requested downsweep time {time_down}s is invalid (must be > 0).')
        # Check if repump time is nonzero
        if time_repump < 0:
            raise ValueError(f'Requested repump time {time_repump} is invalid (must be non-negative).')

        # Compute the time per sample on the up/down sweep
        self.time_per_subpixel_up = time_up / self.n_subpixels_up
        self.time_per_subpixel_down = time_down / self.n_subpixels_down
        # Compute the number of clock cycles for each step, 
        self.cycles_per_subpixel_up = round(self.time_per_subpixel_up * self.clock_rate)
        self.cycles_per_subpixel_down = round(self.time_per_subpixel_down * self.clock_rate)
        self.cycles_per_repump = round(time_repump * self.clock_rate)

        # Raise warnings if the clock rate is too slow
        if self.cycles_per_repump < 5:
            logger.warning(
                f'Clock cycles during repump ({self.cycles_per_repump}) is less than 5, timing error may exceed 10%.'
            )
        if self.cycles_per_subpixel_up < 5:
            logger.warning(
                f'Clock cycles per subpixel up ({self.cycles_per_subpixel_up}) is less than 5, timing error may exceed 10%.'
            )
        if self.cycles_per_subpixel_down < 5:
            logger.warning(
                f'Clock cycles per subpixel down ({self.cycles_per_subpixel_down}) is less than 5, timing error may exceed 10%.'
            )
        
        # Compute the number of samples
        self.n_samples_repump = self.cycles_per_repump
        self.n_samples_upscan = self.cycles_per_subpixel_up * n_pixels_up * n_subpixels
        self.n_samples_downscan = self.cycles_per_subpixel_down * n_pixels_down * n_subpixels 
        self.n_samples_scan = self.n_samples_upscan + self.n_samples_downscan
        self.n_samples_total = self.n_samples_repump + self.n_samples_upscan + self.n_samples_downscan

        # Compute output datastream for the scanning laser
        subpixel_values_up = np.linspace(start=min, stop=max, num=n_pixels_up*n_subpixels, endpoint=False)
        subpixel_values_down = np.linspace(start=max, stop=min, num=n_pixels_down*n_subpixels, endpoint=False)
        # Sample values are what data is actually written to the scan_laser
        # In this implementation the laser is held at the subpixel value for the associated number 
        # of clock cycles.
        scan_samples_up = np.repeat(a=subpixel_values_up, repeats=self.cycles_per_subpixel_up) 
        scan_samples_down = np.repeat(a=subpixel_values_down, repeats=self.cycles_per_subpixel_down)
        # Sample values during the repump step are held to the minimum value
        scan_samples_repump = np.ones(self.n_samples_repump) * min
        # Combine to get the scan laser output
        scan_laser_output = np.concatenate(
            arrays=[scan_samples_repump, scan_samples_up, scan_samples_down]
        )

        # Compute output datstream for the repump laser
        # Laser is on during the repump step and off otherwise
        repump_samples_repump = np.ones(self.n_samples_repump) * self.repump_laser_setpoints['on']
        repump_samples_scan = np.ones(self.n_samples_scan) * self.repump_laser_setpoints['off']
        # Combine to get repump laser output
        repump_laser_output = np.concatenate(
            arrays=[repump_samples_repump, repump_samples_scan]
        )

        # Save the output datastreams
        self.output_data = {
            self.scan_laser_id: scan_laser_output,
            self.repump_laser_id: repump_laser_output 
        }
        # Perform a soft start on both
        self.soft_start = {
            self.scan_laser_id: True,
            self.repump_laser_id: True
        }

        # In this implementation the input datastreams should begin recording data after the repump.
        # They are also all treated the same and so we assign the same values for `n_samples` and
        # the corresponding readout delays
        self.input_samples = {
            id: self.n_samples_scan for id in self.inputs
        }
        self.readout_delays = {
            id: self.n_samples_repump for id in self.inputs
        }

        # Estimate the complete repump + scan cycle time and set the timeout (add 1 second buffer)
        self.timeout = self.n_samples_total / self.clock_rate + 1


    def process_data(
            self,
            data: dict[str,np.ndarray],
            instructions: dict[str,str]
    ) -> dict[str, np.ndarray]:
        '''
        Process the data to return values in terms of the subpixels and pixels rather than clock
        cycles.

        Options:
            (1) `'sum'`: report the sum of the samples
            (2) `'average'`: average the samples in 
            (3) `'first'`: report the first sample (default behavior)
        '''

        # Dictionary to save the data in
        output_dict = {}

        for name in data:

            # Split the data into upscan and downscan then reshape into 2-d array with shape
            # `(n_subpixels, cycles_per_subpixel)`.
            subpixel_data_up = data[name][self.n_samples_repump:self.n_samples_repump+self.n_samples_upscan]
            subpixel_data_up_reshaped = subpixel_data_up.reshape(
                self.n_subpixels_up, self.cycles_per_subpixel_up
            )
            subpixel_data_down = data[name][self.n_samples_repump:self.n_samples_repump+self.n_samples_upscan]
            subpixel_data_down_reshaped = subpixel_data_down.reshape(
                self.n_subpixels_up, self.cycles_per_subpixel_up
            )

            if (name not in instructions) or (instructions[name] == 'first'):
                # Get the first data point of each subpixel
                output_dict[name+'_subpixel_up'] = subpixel_data_up_reshaped[:,0].squeeze()
                output_dict[name+'_subpixel_down'] = subpixel_data_down_reshaped[:,0].squeeze()
                output_dict[name+'_subpixel'] = np.concatenate(
                    arrays=[ output_dict[name+'_subpixel_up'], output_dict[name+'_subpixel_down'] ]
                )
                # Compute the values at the pixels
                output_dict[name+'_up'] = output_dict[name+'_subpixel_up'].reshape(
                        self.n_pixels_up, self.n_subpixels)[:,0].squeeze()
                output_dict[name+'_down'] = output_dict[name+'_subpixel_down'].reshape(
                        self.n_pixels_up, self.n_subpixels)[:,0].squeeze()
                output_dict[name] = np.concatenate(
                    arrays=[ output_dict[name+'_up'], output_dict[name+'_down'] ]
                )
            # Else if 'sum' take the sum
            elif instructions[name] == 'sum':
                output_dict[name+'_subpixel_up'] = np.sum(subpixel_data_up_reshaped, axis=1).squeeze()
                output_dict[name+'_subpixel_down'] = np.sum(subpixel_data_down_reshaped, axis=1).squeeze()
                output_dict[name+'_subpixel'] = np.concatenate(
                    arrays=[ output_dict[name+'_subpixel_up'], output_dict[name+'_subpixel_down'] ]
                )
                # Compute the values at the pixels
                output_dict[name+'_up'] = np.sum(
                    output_dict[name+'_subpixel_up'].reshape(self.n_pixels_up, self.n_subpixels),
                    axis=1
                ).squeeze()
                output_dict[name+'_down'] = np.sum(
                    output_dict[name+'_subpixel_down'].reshape(self.n_pixels_down, self.n_subpixels),
                    axis=1
                ).squeeze()
                output_dict[name] = np.concatenate(
                    arrays=[ output_dict[name+'_up'], output_dict[name+'_down'] ]
                )
            # Else if 'average' take the average
            elif instructions[name] == 'average':
                output_dict[name+'_subpixel_up'] = np.average(subpixel_data_up_reshaped, axis=1).squeeze()
                output_dict[name+'_subpixel_down'] = np.average(subpixel_data_down_reshaped, axis=1).squeeze()
                output_dict[name+'_subpixel'] = np.concatenate(
                    arrays=[ output_dict[name+'_subpixel_up'], output_dict[name+'_subpixel_down'] ]
                )
                # Compute the values at the pixels
                output_dict[name+'_up'] = np.average(
                    output_dict[name+'_subpixel_up'].reshape(self.n_pixels_up, self.n_subpixels),
                    axis=1
                ).squeeze()
                output_dict[name+'_down'] = np.average(
                    output_dict[name+'_subpixel_down'].reshape(self.n_pixels_down, self.n_subpixels),
                    axis=1
                ).squeeze()
                output_dict[name] = np.concatenate(
                    arrays=[ output_dict[name+'_up'], output_dict[name+'_down'] ]
                )
            # Raise error if instruction is invalid
            else:
                raise ValueError(f'Instruction {instructions[name]} invalid.')
            
        # Return the output dictionary
        return output_dict
    



class PLEControllerPulsedRepumpSegmented(SequenceControllerBase):
    '''
    This version of the PLE controller splits the sequence into three separate segments, each of
    which are set by a separate `NidaqSequencer`. The three segments, corresponding to repump, 
    upscan, and downscan, are then run in sequence repeatedly to generate the data. This avoids the 
    awkward conversion between the clock and sample rates, and subsequent back conversion after
    reading out the data. The cost, however, is increased timing uncertainty between each segment.
    Fortunately, the overhead between segements is only due to writing the new set of instructions
    to the DAQ which is generally fast and would not impact the run time very much if at all.

    Unfortunately, the use of multiple `NidaqSequencer` instances for each segment requires a
    substantial modification to the underlying `SequenceControllerBase` class. Nevertheless, we
    retain this inheritence to indicate that the same class structure should be retained.
    '''

    def __init__(
            self,
            scan_inputs: dict[str,NidaqSequencerInputGroup],
            scan_outputs: dict[str,NidaqSequencerOutputGroup],
            repump_inputs: dict[str,NidaqSequencerInputGroup],
            repump_outputs: dict[str,NidaqSequencerOutputGroup],
            scan_laser_id: str,
            repump_laser_id: str,
            counter_id: str,
            repump_laser_setpoints: dict = {'on': 1, 'off':0},
            scan_clock_device: str = 'Dev1',
            scan_clock_channel: str = 'port0',
            scan_clock_terminal: str = 'PFI12',
            repump_clock_device: str = 'Dev1',
            repump_clock_channel: str = 'port0',
            repump_clock_terminal: str = 'PFI12',
            process_instructions: dict = {}
    ):
        # Save the settings
        self.scan_inputs = scan_inputs
        self.scan_outputs = scan_outputs
        self.scan_clock_device = scan_clock_device
        self.scan_clock_channel  = scan_clock_channel
        self.scan_clock_terminal = scan_clock_terminal
        self.repump_inputs = repump_inputs
        self.repump_outputs = repump_outputs
        self.repump_clock_device = repump_clock_device
        self.repump_clock_channel  = repump_clock_channel
        self.repump_clock_terminal = repump_clock_terminal

        # Instantiate the sequencers for the repump, upscan, and downscan
        self.repump_sequencer = NidaqSequencer(
            inputs = repump_inputs,
            outputs = repump_outputs,
            clock_device = repump_clock_device,
            clock_channel = repump_clock_channel,
            clock_terminal = repump_clock_terminal
        )
        self.upscan_sequencer = NidaqSequencer(
            inputs = scan_inputs,
            outputs = scan_outputs,
            clock_device = scan_clock_device,
            clock_channel = scan_clock_channel,
            clock_terminal = scan_clock_terminal
        )
        self.downscan_sequencer = NidaqSequencer(
            inputs = scan_inputs,
            outputs = scan_outputs,
            clock_device = scan_clock_device,
            clock_channel = scan_clock_channel,
            clock_terminal = scan_clock_terminal
        )

        # Other attributes to be utilized later
        self.sequence_settings = None
        self.sample_rate_repump = None
        self.sample_rate_upscan = None
        self.sample_rate_downscan = None

        self.output_data_repump = None
        self.output_data_upscan = None
        self.output_data_downscan = None
        
        self.input_samples_repump = None
        self.input_samples_upscan = None
        self.input_samples_downscan = None
        self.readout_delays = None
        self.soft_start = None
        self.timeout_repump = None
        self.timeout_upscan = None
        self.timeout_downscan = None

        # Control attributes
        self.busy = False       # True if currently executing an action
        self.stop = False       # Set to `True` externally if controller should stop

        self.scan_laser_id = scan_laser_id
        self.repump_laser_id = repump_laser_id
        self.counter_id = counter_id
        self.repump_laser_setpoints = repump_laser_setpoints
        self.process_instructions = process_instructions

    def configure_sequence(
            self,
            min,
            max,
            n_pixels_up,
            n_pixels_down,
            n_subpixels,
            time_up,
            time_down,
            time_repump,
    ):
        '''
        In this current implementation, it is assumed that only the `repump_laser` is included as
        an output for the repump. Likewise, it is assumed that only the `scan_laser` is included as
        an output for the scan.
        '''
        # Save the scan parameters
        self.min=min
        self.max=max
        self.n_pixels_up=n_pixels_up
        self.n_pixels_down=n_pixels_down
        self.n_subpixels=n_subpixels
        self.n_subpixels_up=n_subpixels*n_pixels_up
        self.n_subpixels_down=n_subpixels*n_pixels_down
        self.time_up=time_up
        self.time_down=time_down
        self.time_repump=time_repump

        self.sequence_settings = {
            'min': self.min,
            'max': self.max,
            'n_pixels_up': self.n_pixels_up,
            'n_pixels_down': self.n_pixels_down,
            'n_subpixels': self.n_subpixels,
            'n_subpixels_up': self.n_subpixels_up,
            'n_subpixels_down': self.n_subpixels_down,
            'time_up': self.time_up,
            'time_down': self.time_down,
            'time_repump': self.time_repump,
        }

        # Check if the max > min and both are within the scan laser's range
        if max > min:
            self.upscan_sequencer.validate_output_data(output_name=self.scan_laser_id,data=min)
            self.upscan_sequencer.validate_output_data(output_name=self.scan_laser_id,data=max)
        else:
            raise ValueError(f'Requested max {max:.3f} is less than min {min:.3f}.')
        # Check if pixel numbers are positive integers
        if type(n_pixels_up) is not int or n_pixels_up < 1:
            raise ValueError(f'Requested # pixels up {n_pixels_up} is invalid (must be at least 1).')
        if type(n_pixels_down) is not int or n_pixels_down < 1:
            raise ValueError(f'Requested # pixels down {n_pixels_down} is invalid (must be at least 1).')
        if type(n_subpixels) is not int or n_subpixels < 1:
            raise ValueError(f'Requested # subpixels {n_subpixels} is invalid (must be at least 1).')
        # Check that up/downscan times are greater than zero.
        if not (time_up > 0):
            raise ValueError(f'Requested upsweep time {time_up}s is invalid (must be > 0).')
        if not (time_down > 0):
            raise ValueError(f'Requested downsweep time {time_down}s is invalid (must be > 0).')
        # Check if repump time is nonzero
        if time_repump < 0:
            raise ValueError(f'Requested repump time {time_repump} is invalid (must be non-negative).')

        # Compute the number of samples
        self.n_samples_repump = int(time_repump * 1000) + 1 # additional sample to shut off the laser
        self.n_samples_upscan = n_pixels_up * n_subpixels
        self.n_samples_downscan = n_pixels_down * n_subpixels 
        self.n_samples_scan = self.n_samples_upscan + self.n_samples_downscan
        self.n_samples_total = self.n_samples_repump + self.n_samples_upscan + self.n_samples_downscan

        # Compute the sample rates
        self.sample_rate_repump = 1000
        self.sample_rate_upscan = self.n_samples_upscan / time_up
        self.sample_rate_downscan = self.n_samples_downscan / time_down

        # Compute output datastream for the scanning laser
        scan_samples_upscan = np.linspace(start=min, stop=max, num=self.n_samples_upscan, endpoint=False)
        scan_samples_downscans = np.linspace(start=max, stop=min, num=self.n_samples_downscan, endpoint=False)

        # Compute output datstream for the repump laser
        # Laser is on during the repump step and shut off for the last two steps
        repump_samples_repump = np.array(
            [self.repump_laser_setpoints['on'],]*(self.n_samples_repump-1) + [self.repump_laser_setpoints['off'],]*2,
            dtype=np.float64
        )

        # Save the output datastreams
        self.output_data_repump = {
            self.repump_laser_id: repump_samples_repump,
        }
        self.output_data_upscan = {
            self.scan_laser_id: scan_samples_upscan,
        }
        self.output_data_downscan = {
            self.scan_laser_id: scan_samples_downscans,
        }
        # Perform a soft start in general
        self.soft_start = {
            self.scan_laser_id: True,
            self.repump_laser_id: True
        }
        # Inputs are all treated the same and so we assign the same values for `n_samples` and
        # the corresponding readout delays
        self.input_samples_repump = {
            id: self.n_samples_repump for id in self.repump_sequencer.input_channels_group
        }
        self.input_samples_upscan = {
            id: self.n_samples_upscan for id in self.upscan_sequencer.input_channels_group
        }
        self.input_samples_downscan = {
            id: self.n_samples_downscan for id in self.downscan_sequencer.input_channels_group
        }
        # No readout delays for now.
        self.readout_delays = {id: 0 for id in self.upscan_sequencer.input_channels_group} | {id: 0 for id in self.repump_sequencer.input_channels_group}
        # Estimate the complete repump + scan cycle time and set the timeout (add 1 second buffer)
        self.timeout_repump = time_repump + 1
        self.timeout_upscan = time_up + 1
        self.timeout_downscan = time_down + 1

    def _run_sequence(
            self, 
            process_method: Callable = None,
            process_kwargs: dict = {}
    ) -> Union[dict[str,np.ndarray], Any]:
        
        # Run the repump sequence
        logger.info('Starting repump...')
        self.repump_sequencer.run_sequence(
            clock_rate=self.sample_rate_repump,
            output_data=self.output_data_repump,
            input_samples=self.input_samples_repump,
            readout_delays=self.readout_delays,
            soft_start=self.soft_start,
            timeout=self.timeout_repump
        )
        logger.info('Finished repump.')
        # Get the data as a dictionary with names appended with repump/upscan/downscan
        repump_data = {
            'repump_'+id: val for id,val in self.repump_sequencer.get_data().items()
        }

        # Run the repump sequence
        logger.info('Starting upscan...')
        self.upscan_sequencer.run_sequence(
            clock_rate=self.sample_rate_upscan,
            output_data=self.output_data_upscan,
            input_samples=self.input_samples_upscan,
            readout_delays=self.readout_delays,
            soft_start=self.soft_start,
            timeout=self.timeout_upscan
        )
        logger.info('Finished upscan.')
        # Get the data
        upscan_data = {
            'upscan_subpixel_'+id: val for id,val in self.upscan_sequencer.get_data().items()
        }

        # Run the repump sequence
        logger.info('Starting downscan...')
        self.downscan_sequencer.run_sequence(
            clock_rate=self.sample_rate_downscan,
            output_data=self.output_data_downscan,
            input_samples=self.input_samples_downscan,
            readout_delays=self.readout_delays,
            soft_start=self.soft_start,
            timeout=self.timeout_downscan
        )
        logger.info('Finished downscan.')
        # Get the data
        downscan_data = {
            'downscan_subpixel_'+id: val for id,val in self.downscan_sequencer.get_data().items()
        }
        # Combine
        data = {**repump_data, **upscan_data, **downscan_data}

        # Return the data dictionary if no process method is provided
        if process_method is None:
            return data
        else:
            # Otherwise return the processed data
            return process_method(data, **process_kwargs)
        
    def process_data(
            self,
            data: dict[str,np.ndarray],
            instructions: dict[str,str]
    ) -> dict[str, np.ndarray]:
        '''
        Process the data to return values in terms of the subpixels and pixels rather than clock
        cycles.

        Options:
            (1) `'sum'`: report the sum of the samples
            (2) `'average'`: average the samples in 
            (3) `'first'`: report the first sample (default behavior)
        '''

        # Dictionary to save the data in
        output_dict = {}

        # Get the names of the inputs and outputs
        source_names = [key for key in self.upscan_sequencer.input_channels_group] + [key for key in self.upscan_sequencer.output_channels_group]

        # Iterate through the names of the sources to process the subpixels
        for name in source_names:

            # Reshape the data
            upscan_data_reshaped = data['upscan_subpixel_'+name].reshape(self.n_pixels_up, self.n_subpixels)
            downscan_data_reshaped = data['downscan_subpixel_'+name].reshape(self.n_pixels_down, self.n_subpixels)

            # Extract data as instructed
            if (name not in instructions) or (instructions[name] == 'first'):
                # Get the first data point of each subpixel
                output_dict['upscan_'+name] = upscan_data_reshaped[:,0].squeeze()
                output_dict['downscan_'+name] = downscan_data_reshaped[:,0].squeeze()
            elif instructions[name] == 'last':
                # Get the last data point of each subpixel
                output_dict['upscan_'+name] = upscan_data_reshaped[:,-1].squeeze()
                output_dict['downscan_'+name] = downscan_data_reshaped[:,-1].squeeze()
            elif instructions[name] == 'sum':
                # Get the sum of the data points at each subpixel
                output_dict['upscan_'+name] = np.sum(upscan_data_reshaped, axis=1).squeeze()
                output_dict['downscan_'+name] = np.sum(downscan_data_reshaped, axis=1).squeeze()
            elif instructions[name] == 'average':
                # Get the average of the data points at each subpixel
                output_dict['upscan_'+name] = np.average(upscan_data_reshaped, axis=1).squeeze()
                output_dict['downscan_'+name] = np.average(downscan_data_reshaped, axis=1).squeeze()
            else:
                ValueError(f'Instruction {instructions[name]} invalid.')

            # Combined data
            output_dict[name] = np.concatenate([ output_dict['upscan_'+name], output_dict['downscan_'+name] ])

        # Add the raw unprocessed data
        output_dict |= data

        # Return the data
        return output_dict

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
        # Attempt to set the value of the specified output to the set point using the repump sequencer
        try:
            self.repump_sequencer.set_output(output_name = output_id, setpoint=setpoint)
        except KeyError:
            # Attempt to set the value using the upscan sequencer
            try:
                self.upscan_sequencer.set_output(output_name = output_id, setpoint=setpoint)
            except Exception as e:
                raise e
        except Exception as e:
            # Catch any other errors
            raise e
        finally:
            # Release the controller
            self.busy=False


class PLEControllerPulsedRepumpSegmentedWithWavemeter(PLEControllerPulsedRepumpSegmented):

    def __init__(
            self,
            scan_inputs: dict[str,NidaqSequencerInputGroup],
            scan_outputs: dict[str,NidaqSequencerOutputGroup],
            repump_inputs: dict[str,NidaqSequencerInputGroup],
            repump_outputs: dict[str,NidaqSequencerOutputGroup],
            scan_laser_id: str,
            repump_laser_id: str,
            counter_id: str,
            nondaq_devices: list[str],
            wavemeter: WavemeterController,
            repump_laser_setpoints: dict = {'on': 1, 'off':0},
            scan_clock_device: str = 'Dev1',
            scan_clock_channel: str = 'port0',
            scan_clock_terminal: str = 'PFI12',
            repump_clock_device: str = 'Dev1',
            repump_clock_channel: str = 'port0',
            repump_clock_terminal: str = 'PFI12',
            nondaq_query_delay: float = 0.1,
            process_instructions: dict = {}
    ):
        super().__init__(
            scan_inputs = scan_inputs,
            scan_outputs = scan_outputs,
            repump_inputs = repump_inputs,
            repump_outputs = repump_outputs,
            scan_laser_id = scan_laser_id,
            repump_laser_id = repump_laser_id,
            counter_id = counter_id,
            repump_laser_setpoints = repump_laser_setpoints,
            scan_clock_device = scan_clock_device,
            scan_clock_channel = scan_clock_channel,
            scan_clock_terminal = scan_clock_terminal,
            repump_clock_device = repump_clock_device,
            repump_clock_channel = repump_clock_channel,
            repump_clock_terminal = repump_clock_terminal,
            process_instructions = process_instructions,
        )
        # Nondaq device names
        self.nondaq_devices = nondaq_devices
        # Wavemeter controller class
        self.wavemeter = wavemeter
        # Delay between queries of non-daq hardware
        self.nondaq_query_delay = nondaq_query_delay
        # Flag set to False when we want the wavemeter to stop reading in data
        self.query_wavemeter = False
        # Data buffers for the wavemeter output timetags and values on the current thread
        self.last_thread_wavemeter_tags = []
        self.last_thread_wavemeter_vals = []

        # Size of the buffer for the up/downscan
        self.upscan_query_buffer_size = None
        self.downscan_query_buffer_size = None

    def configure_sequence(
            self,
            min,
            max,
            n_pixels_up,
            n_pixels_down,
            n_subpixels,
            time_up,
            time_down,
            time_repump,
    ):
        super().configure_sequence(
                min,
                max,
                n_pixels_up,
                n_pixels_down,
                n_subpixels,
                time_up,
                time_down,
                time_repump,
        )

        # Need to additionally determine the buffersize since the number of wavemeter queries varies
        # depending on random delays in the serial protocol.
        self.upscan_query_buffer_size = int(time_up / self.nondaq_query_delay) + 1
        self.downscan_query_buffer_size = int(time_down / self.nondaq_query_delay) + 1

    def _run_sequence(
            self, 
            process_method: Callable = None,
            process_kwargs: dict = {}
    ) -> Union[dict[str,np.ndarray], Any]:
        '''
        Runs the sequence of repump, upscan, and downscan in sequence.
        In this version includes intermediate steps to track the wavelength position between the
        start and stop of the up/downsweeps to launch a thread to monitor the wavemeter.
        '''
        # Open the wavemeter connection
        self.wavemeter.open()

        # Run the repump sequence
        logger.info('Starting repump...')
        self.repump_sequencer.run_sequence(
            clock_rate=self.sample_rate_repump,
            output_data=self.output_data_repump,
            input_samples=self.input_samples_repump,
            readout_delays=self.readout_delays,
            soft_start=self.soft_start,
            timeout=self.timeout_repump
        )
        logger.info('Finished repump.')
        # Get the data as a dictionary with names appended with repump/upscan/downscan
        repump_data = {
            'repump_'+id: val for id,val in self.repump_sequencer.get_data().items()
        }

        # Create the thread to watch the wavemeter thread and start it.
        # The thread will immediately start to collect the data from the wavemeter.
        # The main thread (that runs this function) will continue on to start the upscan sequence
        wavemeter_thread = Thread(target=self._wavemeter_query_thread_function)
        wavemeter_thread.start()
        # Run the repump sequence
        logger.info('Starting upscan...')
        self.upscan_sequencer.run_sequence(
            clock_rate=self.sample_rate_upscan,
            output_data=self.output_data_upscan,
            input_samples=self.input_samples_upscan,
            readout_delays=self.readout_delays,
            soft_start=self.soft_start,
            timeout=self.timeout_upscan
        )
        # Stop the wavemeter thread by setting the flag
        self.query_wavemeter = False
        # Wait for the wavemeter thread to end -- this pauses the main thread until it finishes
        # This is necessary so we don't start it again before it finishes.
        wavemeter_thread.join()
        # Log the upscan completion
        logger.info('Finished upscan.')
        # Get the data
        upscan_data = {
            'upscan_subpixel_'+id: val for id,val in self.upscan_sequencer.get_data().items()
        }
        # Add the wavemeter tags and values to the upscan data dictionary
        upscan_data['upscan_wavemeter_tags'] = np.pad(
            np.array(self.last_thread_wavemeter_tags, dtype=np.float32),
            pad_width=(0,self.upscan_query_buffer_size - len(self.last_thread_wavemeter_tags)),
            mode='constant',
            constant_values=np.nan)
        upscan_data['upscan_wavemeter_vals'] = np.pad(
            self.last_thread_wavemeter_vals,
            pad_width=(0,self.upscan_query_buffer_size - len(self.last_thread_wavemeter_vals)),
            mode='constant',
            constant_values=np.nan)

        # Create the thread to watch the wavemeter thread and start it again for the down scan.
        wavemeter_thread = Thread(target=self._wavemeter_query_thread_function)
        wavemeter_thread.start()
        # Run the repump sequence
        logger.info('Starting downscan...')
        self.downscan_sequencer.run_sequence(
            clock_rate=self.sample_rate_downscan,
            output_data=self.output_data_downscan,
            input_samples=self.input_samples_downscan,
            readout_delays=self.readout_delays,
            soft_start=self.soft_start,
            timeout=self.timeout_downscan
        )
        # Stop the wavemeter thread by setting the flag
        self.query_wavemeter = False
        # Wait for the wavemeter thread to end -- this pauses the main thread until it finishes
        # This is necessary so we don't start it again before it finishes.
        wavemeter_thread.join()
        # Log the downscan completion
        logger.info('Finished downscan.')
        # Get the data
        downscan_data = {
            'downscan_subpixel_'+id: val for id,val in self.downscan_sequencer.get_data().items()
        }
        # Add the wavemeter tags and values to the downscan data dictionary
        downscan_data['downscan_wavemeter_tags'] = np.pad(
            np.array(self.last_thread_wavemeter_tags, dtype=np.float32),
            pad_width=(0,self.downscan_query_buffer_size - len(self.last_thread_wavemeter_tags)),
            mode='constant',
            constant_values=np.nan)
        downscan_data['downscan_wavemeter_vals'] = np.pad(
            self.last_thread_wavemeter_vals,
            pad_width=(0,self.downscan_query_buffer_size - len(self.last_thread_wavemeter_vals)),
            mode='constant',
            constant_values=np.nan)

        # Combine
        data = {**repump_data, **upscan_data, **downscan_data}

        # Close the wavemeter connection, freeing it up for other applications
        self.wavemeter.close()

        # Return the data dictionary if no process method is provided
        if process_method is None:
            return data
        else:
            # Otherwise return the processed data
            return process_method(data, **process_kwargs)
        

    def _wavemeter_query_thread_function(
            self
    ):
        '''
        Repeatedly queries the wavemeter for data until the flag is set to false
        '''
        # Set the flag to start querying the wavemeter
        self.query_wavemeter = True
        # Reset the current scan wavemeter output buffers
        self.last_thread_wavemeter_tags = []
        self.last_thread_wavemeter_vals = []
        # Until the flag is set to false get the data from the wavemeter
        while self.query_wavemeter:
            # Try to get the data from the wavemeter
            try:
                # Attempt to readout the wavemeter
                tag, val = self.wavemeter.readout()
                # Append the results
                self.last_thread_wavemeter_tags.append(tag)
                self.last_thread_wavemeter_vals.append(val)
            # Catch excpetions (i.e. if the wavemeter hasn't gotten a new value to output yet)
            except Exception as e:
                logger.debug('Wavemeter readout error:', e)
            # Wait for the delay (accounts for finite delay between subsequent wavemeter readout)
            time.sleep(self.nondaq_query_delay)