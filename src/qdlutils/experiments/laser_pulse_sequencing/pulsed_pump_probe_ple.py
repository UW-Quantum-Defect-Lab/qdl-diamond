import logging
import os
import numpy as np
import matplotlib.pyplot as plt
import time
import h5py
import nidaqmx
import threading

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

from scipy.interpolate import make_smoothing_spline
from scipy.signal import find_peaks

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class PulsedPLE(SequenceControllerBase):

    def __init__(
            self,
            repump_id: str,
            repump_do_config: dict,
            probe_id: str,
            probe_do_config: dict,
            probe_ao_config: dict,
            pump_id: str,
            pump_do_config: dict,
            counter_id: str,
            counter_ci_config: dict,
            wavemeter_controller: WavemeterController,
            clock_device: str = 'Dev1',
            clock_channel: str = 'ctr0',
    ):
        # Save supplied parameters not used in the parent class
        self.repump_id = repump_id
        self.probe_id = probe_id
        self.pump_id = pump_id
        self.counter_id =counter_id
        # Save the configurations
        self.repump_do_config = repump_do_config
        self.probe_do_config = probe_do_config
        self.probe_ao_config = probe_ao_config
        self.pump_do_config = pump_do_config
        self.counter_ci_config = counter_ci_config
        # Wavemeter controller class for interfacing with the wavemeter
        self.wavemeter_controller = wavemeter_controller

        # Generate the inputs for the measurement sequencer
        sequence_inputs = {
            'ci_edge_group' : NidaqSequencerCIEdgeRateGroup(
                channels_config  = {
                    counter_id : counter_ci_config
                },
            )
        }
        # Generate the outputs for the measurement sequencer
        sequence_outputs = {
            'do_group' : NidaqSequencerDO32LineGroup(
                channels_config = {
                    repump_id : repump_do_config,
                    probe_id  : probe_do_config,
                    pump_id   : pump_do_config
                }
            ),
            'ao_group' : NidaqSequencerAOVoltageGroup(
                channels_config = {
                    probe_id+'_freq' : probe_ao_config
                }
            ),
        }

        super().__init__(
            inputs = sequence_inputs,
            outputs = sequence_outputs,
            clock_device = clock_device,
            clock_channel = clock_channel,
        )

        # Initialize the probe voltage to zero to start and initialize the probe frequency
        self.probe_voltage = 0
        self.set_probe_voltage_smooth(setpoint=0)

        # Flags
        self.query_wavemeter = False

        # Data
        self.wavemeter_tags = []
        self.wavemeter_vals = []
        self.data = {} # Keys are different datasets
        self.scan_parameters = {}

    def set_probe_voltage_smooth(
            self,
            setpoint: float,
            max_voltage_step: float = 0.01,
            move_speed: float = 4,
            move_time: float = None,
    ):
        '''
        Sets the value of the probe voltage to `setpoint` by continuously scanning the voltage from
        the current position. Then records the setpoint.

        We need to program this at the hardware level since we don't want the other components of
        the sequencer to be utilized.

        Parameters
        ----------
        setpoint: float
            The voltage to set to.
        max_voltage_step: float = 0.1
            The maximum change in voltage per step.
        move_speed: float = 1
            The speed to move at in volts/second.
        move_time: float = None
            If provided, overwrites the move speed such that the entire move occurs in `move_time`
            seconds.
        '''
        # Validate the data
        self.sequencer.validate_output_data(output_name=self.probe_id+'_freq', data=setpoint)
        # If already at setpoint exit
        if self.probe_voltage == setpoint:
            print('Already at setpoint.')
            return None

        # Get the number of samples to scan, should be at least 2 steps
        n_samples = max(4, int(np.abs(self.probe_voltage - setpoint) / max_voltage_step))
        # Get the voltages to scan over
        voltages = np.linspace(self.probe_voltage, setpoint, n_samples, endpoint=True)
        # If the move time is provided, set the rate accordingly
        if move_time is not None:
            sample_rate = n_samples / move_time
        # else the move speed is utilized
        else:
            # Determine the voltage spacing
            dvoltage = np.abs(voltages[1] - voltages[0])
            # Determine the sample rate from the move speed
            sample_rate = move_speed / dvoltage
        # Validate the data again
        self.sequencer.validate_output_data(output_name=self.probe_id+'_freq', data=voltages)

        # Create an internally timed task to perform the move
        with nidaqmx.Task() as task:

            # Create the AO voltage channel and configure the timing
            task.ao_channels.add_ao_voltage_chan(self.probe_ao_config['device']+'/'+self.probe_ao_config['channel'])
            task.timing.cfg_samp_clk_timing(
                sample_rate,
                sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
                samps_per_chan=n_samples
            )
            # Write the data to the AO channel
            task.write(voltages)
            # Start the AO task
            task.start()
            # Wait until done
            task.wait_until_done(timeout=n_samples*sample_rate + 1) # 1 second buffer
            # Stop the task
            task.stop()

        # Update the current position
        self.probe_voltage = setpoint
    
    def configure_sequence(
            self,
            pump: bool,
            voltage_min: float,
            voltage_max: float,
            num_pixels: int,
            repump_time: float, # in ms
            read_time: float,   # in ms
            direction: str = 'up'
    ):
        # Verify the data
        if voltage_max > voltage_min:
            self.sequencer.validate_output_data(output_name=self.probe_id+'_freq', data=voltage_min)
            self.sequencer.validate_output_data(output_name=self.probe_id+'_freq', data=voltage_max)
        else:
            raise ValueError(f'Requested max {voltage_max:.3f} is less than min {voltage_min:.3f}.')
        if num_pixels < 1:
            raise ValueError('# pixels must be greater than 1.')
        if read_time < 0 or read_time > 10000:
            raise ValueError('Scan time must be between more than 0 and less than 10 second.')
        if repump_time < 0 or repump_time > 10000:
            raise ValueError('Repump time must be non-negative and less than 10 seconds.') 
        
        # Clock rate is constant to give 100 us steps.
        clock_rate = 10000 # 1 kHz

        # Laser pulse sequence per pixel
        time_per_pixel = 1e-3 * (repump_time + read_time) # in s
        clock_cycles_per_pixel = int(clock_rate * time_per_pixel)
        clock_cycles_repump = int(1e-3 * repump_time * clock_rate)
        # Generate the data
        repump_data_per_pixel = np.zeros(clock_cycles_per_pixel)
        repump_data_per_pixel[:clock_cycles_repump] = 1             # Repump is on for the first part
        probe_data_per_pixel = np.zeros(clock_cycles_per_pixel)
        probe_data_per_pixel[clock_cycles_repump:] = 1              # Probe is on the last part
        pump_data_per_pixel = np.zeros(clock_cycles_per_pixel)
        if pump:
            pump_data_per_pixel[clock_cycles_repump:] = 1           # Pump is on the last part (if specified)
        
        # Total sequence data
        num_samples = clock_cycles_per_pixel * num_pixels         # Total number of samples for the scan
        # Tile the individual pixel pulse sequence data
        repump_data = np.tile(repump_data_per_pixel, num_pixels)  # Repeats sequence
        probe_data  = np.tile(probe_data_per_pixel, num_pixels)  
        pump_data   = np.tile(pump_data_per_pixel, num_pixels)   

        # Get the voltage 
        voltage_data_at_pixel = np.linspace(voltage_min, voltage_max, num_pixels)
        voltage_data = np.repeat(voltage_data_at_pixel, clock_cycles_per_pixel)
        # Invert the direction if specified
        if direction == 'down':
            voltage_data_at_pixel =  voltage_data_at_pixel[::-1]
            voltage_data = voltage_data[::-1]

        # Set up the sequencer
        self.clock_rate = clock_rate
        self.output_data = {
            self.repump_id        : repump_data,
            self.probe_id         : probe_data,
            self.pump_id          : pump_data,
            self.probe_id+'_freq' : voltage_data
        }
        self.input_samples = {
            self.counter_id : num_samples
        }
        self.readout_delays = {}    # No delays
        self.soft_start = {}        # No soft start
        self.timeout = num_samples / clock_rate + 1    # 1 extra second

        # Save some parameters for later use
        self.pixel_repump_data = repump_data_per_pixel
        self.pixel_probe_data = probe_data_per_pixel
        self.pixel_pump_data = pump_data_per_pixel
        self.pixel_samples = clock_cycles_per_pixel
        self.pixel_repump_end_index = clock_cycles_repump
        self.pixel_time = time_per_pixel
        self.num_pixels = num_pixels
        self.scan_time = time_per_pixel * num_pixels

        '''x = np.linspace(0,time_per_pixel,clock_cycles_per_pixel)
        plt.plot(x,repump_data_per_pixel, label='repump')
        plt.plot(x,probe_data_per_pixel, label='probe')
        plt.plot(x,pump_data_per_pixel, label='pump')
        plt.legend()
        plt.show()

        x = np.linspace(0,scan_time,clock_cycles_per_pixel*num_pixels)
        plt.plot(repump_data, label='repump')
        plt.plot(probe_data, label='probe')
        plt.plot(pump_data, label='pump')
        plt.plot(voltage_data, label='voltage')
        plt.legend()
        plt.show()'''

    def _wavemeter_thread_function(
            self,
    ):
        # Reads the wavemeter continuously in the thread
        '''
        Repeatedly queries the wavemeter for data until the flag is set to false
        '''
        # Set the flag to start querying the wavemeter
        self.query_wavemeter = True
        # Reset the current scan wavemeter output buffers
        self.wavemeter_tags = []
        self.wavemeter_vals = []
        # Until the flag is set to false get the data from the wavemeter
        while self.query_wavemeter:
            # Try to get the data from the wavemeter
            try:
                # Attempt to readout the wavemeter
                tag, val = self.wavemeter_controller.readout()
                # Append the results if valid (zero values are not allowed)
                if val > 100:
                    self.wavemeter_tags.append(tag)
                    self.wavemeter_vals.append(val)
                else:
                    print('Wavemeter readout error: reading value invalid')
            # Catch excpetions (i.e. if the wavemeter hasn't gotten a new value to output yet)
            except Exception as e:
                raise e
                #print('Wavemeter readout error:', e)
            # Wait for the delay (accounts for finite delay between subsequent wavemeter readout)
            time.sleep(0.1)

    def run_scan(
            self,
            pump: bool,
            voltage_min: float,
            voltage_max: float,
            num_pixels: int,
            repump_time: float, # in ms
            read_time: float,   # in ms
            direction: str = 'up'
    ):
        # Configure the sequence
        self.configure_sequence(
            pump        = pump,
            voltage_min = voltage_min,
            voltage_max = voltage_max,
            num_pixels  = num_pixels,
            repump_time = repump_time,
            read_time   = read_time,
            direction   = direction
        )

        # Get the start value to move to between scans.
        self.start_value = voltage_min
        self.end_value = voltage_max
        if direction == 'down':
            # Invert the direction if specified
            self.start_value = voltage_max
            self.end_value = voltage_min

        # Save the configuration parameters
        self.scan_parameters = {
            'pump'        : pump,
            'voltage_min' : voltage_min,
            'voltage_max' : voltage_max,
            'num_pixels'  : num_pixels,
            'repump_time' : repump_time,
            'read_time'   : read_time,
            'direction'   : direction
        }

        # Move to the start position
        self.set_probe_voltage_smooth(self.start_value)
        time.sleep(2) # Wait for the voltage and wavemeter to settle.

        # Start the wavemeter
        self.wavemeter_controller.open()
        # Start the wavemeter thread
        wavemeter_thread = threading.Thread(target=self._wavemeter_thread_function)
        wavemeter_thread.start()

        # Run the sequence
        raw_sequence_data = self._run_sequence()

        # Stop the wavemeter thread by setting the flag
        self.query_wavemeter = False
        # Wait for the wavemeter thread to end -- this pauses the main thread until it finishes
        # This is necessary so we don't start it again before it finishes.
        wavemeter_thread.join()
        # Close the wavemeter
        self.wavemeter_controller.close()

        # Process the data
        self.data = self.process_data(data=raw_sequence_data)

        # Plot the scan
        self.plot_scan_results()

        # Return to start voltage
        self.probe_voltage = self.end_value
        self.set_probe_voltage_smooth(self.start_value)

    def process_data(
            self,
            data: dict[str,np.ndarray],
    ):
        # Reshape the counter data
        counter_data_reshaped = data[self.counter_id].reshape(self.num_pixels, self.pixel_samples)
        # Get the raw counts during the repump/readout steps
        raw_counter_repump = counter_data_reshaped[:,:self.pixel_repump_end_index]
        raw_counter_read = counter_data_reshaped[:,self.pixel_repump_end_index:]
        # Average the counts
        avg_counter_repump = np.average(raw_counter_repump, axis=1).squeeze()
        avg_counter_read = np.average(raw_counter_read, axis=1).squeeze()

        # Get the frequencies
        scan_times = np.linspace(0,self.scan_time,self.num_pixels)
        tags = np.array(self.wavemeter_tags)
        vals = np.array(self.wavemeter_vals)
        # Zero the time tags and rescale to seconds
        tags = (tags - tags[0]) * 0.01 # units are in 10 ms
        # Generate the interpolator and interpolate the frequenices
        interpolator = make_smoothing_spline(tags,vals)
        freqs = interpolator(scan_times)

        output = {
            'counter_data_reshaped' : counter_data_reshaped,
            'raw_counter_repump'    : raw_counter_repump,
            'raw_counter_read'      : raw_counter_read,
            'avg_counter_repump'    : avg_counter_repump,
            'avg_counter_read'      : avg_counter_read,
            'freqs'                 : freqs,
            'wavemeter_tags'        : tags,
            'wavmeter_vals'         : vals
        }
        output |= data
        return output
    
    def locate_peaks(
            self,
            threshold = None
    ):
        xs = self.data['freqs']
        ys = self.data['avg_counter_read']
        if threshold is None:
            # estimate from the data
            threshold = np.max(self.data['avg_counter_read']) / 2
        
        # Calculate frequency spacing
        df = np.min(np.diff(xs))
        # Determine the linewidth in units of samples
        linewidth = max(1, int(0.2/df)) # 100 Mhz / df is number of samples per homogeneous linewidth
        peak_idxs, _ = find_peaks(ys, height=threshold, distance=linewidth)
        peak_freqs = xs[peak_idxs]
        peak_amplitudes = ys[peak_idxs]

        # Print frequencies
        j = 0
        print('Peak\tfrequency (GHz)\twavelength (nm)')
        for x in peak_freqs:
            print(f'{j}' + '\t' + f'{x:.4f}' + '\t' + f'{299792458/x:.6f}')
            j += 1

        # Plot output
        self.plot_scan_results(peaks = (peak_freqs, peak_amplitudes))

    def plot_scan_results(
            self,
            peaks: tuple[float, float] = None
    ):
        fig, ax = plt.subplots(1,1,figsize=(5,4))
        ax.plot(self.data['freqs'], self.data['avg_counter_read'])
        ax.set_xlabel('Frequency (GHz)')
        ax.set_ylabel('Signal (cts/s)')
        ax.grid(alpha=0.3)
        if peaks is not None:
            ax.plot(peaks[0], peaks[1], 'ko')
            j = 0
            for x,y in zip(peaks[0], peaks[1]):
                ax.text(x,y,s=f'{j}')
                j += 1
        plt.show()

    def save(
            self,
            filename: str,
    ):
        # Add the extension
        fname = filename+'.hdf5'

        # Save as hdf5
        print(f'Saving data as `{fname}`.')
        with h5py.File(fname, 'w') as f:

            # Save the scan settings
            # Run through the scan parameters dictionary saving data 
            ds = f.create_dataset('scan_parameters', data=np.array([]))
            for param, val in self.scan_parameters.items():
                ds.attrs[param] =  val

            # Save the data for a single sequence
            f.create_dataset('counter_data_reshaped', data=self.data['counter_data_reshaped'])
            f.create_dataset('raw_counter_repump'   , data=self.data['raw_counter_repump'])
            f.create_dataset('raw_counter_read'     , data=self.data['raw_counter_read'])
            f.create_dataset('avg_counter_repump'   , data=self.data['avg_counter_repump'])
            f.create_dataset('avg_counter_read'     , data=self.data['avg_counter_read'])
            f.create_dataset('freqs'                , data=self.data['freqs'])
            f.create_dataset('wavemeter_tags'       , data=self.data['wavemeter_tags'])
            f.create_dataset('wavmeter_vals'        , data=self.data['wavmeter_vals'])

        print('File saved.')

