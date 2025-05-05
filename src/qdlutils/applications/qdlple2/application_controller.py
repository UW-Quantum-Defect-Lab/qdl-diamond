import logging
import numpy as np

from qdlutils.hardware.nidaq.synchronous.nidaqsequencerinput import NidaqSequencerInput
from qdlutils.hardware.nidaq.synchronous.nidaqsequenceroutput import NidaqSequencerOutput

from qdlutils.experiments.controllers.sequencecontrollerbase import SequenceControllerBase

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class PLEControllerBase(SequenceControllerBase):

    def __init__(
            self,
            inputs: dict[str,NidaqSequencerInput],
            outputs: dict[str,NidaqSequencerOutput],
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




class PLEControllerPulsedRepump(SequenceControllerBase):

    '''
    This class implements the PLE scan controller for PLE experiments with a single pulsed repump at
    the start of each scan. Outputs are limited to the scan laser and the repump laser signals. The
    controller supports an arbitrary number of input sources.
    '''

    def __init__(
            self,
            inputs: dict[str,NidaqSequencerInput],
            outputs: dict[str,NidaqSequencerOutput],
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