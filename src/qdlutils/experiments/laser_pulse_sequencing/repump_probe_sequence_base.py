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

from scipy.optimize import curve_fit

from IPython import display
from typing import Union, Any, Callable

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class RepumpProbeSequenceBase(SequenceControllerBase):

    '''
    This class implements the basic features for pulse sequenc e experiments involving a repump laser
    and probe laser.

    The repump laser does not have any frequency control but is turned on/off via a TTL digital
    output signal.

    The probe laser is also turned on/off via a TTL digital output signal and has frequency control
    via an analog voltage output.

    The counter input channel is connected to the SPCM to readout the signal.
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
        # Save supplied parameters not used in the parent class
        self.repump_id = repump_id
        self.probe_id = probe_id
        self.counter_id =counter_id
        # Save the configurations
        self.repump_do_config = repump_do_config
        self.probe_do_config = probe_do_config
        self.probe_ao_config = probe_ao_config
        self.counter_ci_config = counter_ci_config
        # Wavemeter controller class for interfacing with the wavemeter
        self.wavemeter_controller = wavemeter_controller

        # Attributes for later use
        self.probe_target = None        # Target wavemeter reading to hold the laser at
        self.probe_voltage = None       # Voltage corresponding to the last setpoint
        self.sequence_settings = None   # Dictionary of the settings used in the sequence
        self.data_batches = []          # Data array. Each element in list is a batch, each batch is
                                        # a 2-d array with rows corresponding to a single subsequence.
        self.batch_probe_targets = []   # List of probe wavemeter reading targets for each batch
        # Data vectors
        self.single_sequence_time = None
        self.single_sequence_repump_data = None
        self.single_sequence_probe_data = None
        self.single_sequence_n_samples = None # Number of samples in a single sequence
        # Data for single scans
        self.single_probe_scan_freq = None
        self.single_probe_scan_volt = None
        self.single_probe_scan_data = None
        # Sequence parameters
        self.n_batches = None
        self.n_repetitions = None
        self.clock_rate = None
    
        # Generate the inputs for the measurement sequence
        sequence_inputs = {
            'ci_edge_group' : NidaqSequencerCIEdgeRateGroup(
                channels_config  = {
                    counter_id : counter_ci_config
                },
            )
        }
        # Generate the outputs for the measurement sequence
        sequence_outputs = {
            'do_group' : NidaqSequencerDO32LineGroup(
                channels_config = {
                    repump_id : repump_do_config,
                    probe_id  : probe_do_config
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
        self.set_probe_voltage(setpoint=0)

    def set_probe_voltage(
        self,
        setpoint: float
    ):
        '''
        Sets the value of the probe voltage to `setpoint` and records the setpoint.
        '''
        self.set_output(output_id=self.probe_id+'_freq', setpoint=setpoint)
        self.probe_voltage = setpoint

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

    def set_probe_target(
            self,
            val: float,
    ):
        '''
        Manually sets the target reading for the probe on the wavemeter.

        Parameters
        ----------
        val: float
            Value to set the target probe wavemeter reading value to.
        '''
        self.probe_target = val

    def set_probe_target_as_current(
            self
    ):  
        '''
        Sets the target reading for the wavemeter to the current wavemeter reading
        '''
        self.wavemeter_controller.open()
        time_tag, probe_target = self.wavemeter_controller.readout()
        self.wavemeter_controller.close()
        self.probe_target = probe_target

    def single_probe_scan(
            self,
            voltage_min: float,
            voltage_max: float,
            n_pixels: int,
            scan_time: float,
            repump_time: float,
            optimize: str = None,
            setpoint_offset: float = 0.1
    ):
        '''
        Configures and performs a single probe laser sweep to assist in locating the resonance
        features of interest.
        For simplicity the sweep scans from the `voltage_min` to `voltage_max` only, measuring the
        frequency at the start and end of the scan via the wavemeter.
        After the scan the laser is smoothly returned to the start value (default) or the frequency
        of an estimated peak/dip feature depending on the `optimize` argument value.

        Parameters
        ----------
        voltage_min: float
            Minimum voltage of the scan range
        voltage_max: float
            Maximum voltage of the scan range
        n_pixels: int
            Number of samples to take 
        scan_time: float
            Time in seconds for the scan
        repump_time: float
            Time to repump for in seconds
        optimize: str = None
            Dictates if and how the probe frequency should be optimized. Options are
            - `min`
            - `max`
            - `min_offset`
            - `max_offset`
            - `min_offset_volt`
            - `max_offset_volt`
            The addition of the suffix `_volt` will move the voltage first to get the target 
            frequency rather than estimate the target frequency from the scan itself.
            If `None` or some other keyword then will simply move back to the start position.
        setpoint_offset: float = 0.1
            The amount to offset the setpoint relative to the min/max when using the ``min-offset''
            or ``max-offset'' optimization options.
        '''

        # Verify the data
        if voltage_max > voltage_min:
            self.sequencer.validate_output_data(output_name=self.probe_id+'_freq', data=voltage_min)
            self.sequencer.validate_output_data(output_name=self.probe_id+'_freq', data=voltage_max)
        else:
            raise ValueError(f'Requested max {voltage_max:.3f} is less than min {voltage_min:.3f}.')
        if n_pixels < 1:
            raise ValueError('# pixels must be greater than 1.')
        if scan_time < 0 or scan_time > 300:
            raise ValueError('Scan time must be between more than 0 and less than 300 seconds.')
        if repump_time < 0 or repump_time > 60:
            raise ValueError('Repump time must be non-negative and less than 60 seconds.')        

        # Generate samples for the data, doing 16 subpixels to ensure smooth scanning
        n_samples = 16*n_pixels
        sample_rate = n_samples/scan_time
        probe_freq_data = np.linspace(start=voltage_min, stop=voltage_max, num=n_samples, endpoint=True)
        probe_freq_pixels = np.linspace(voltage_min,voltage_max,n_pixels)
        # Data for the probe and repump swtich data
        probe_data = np.ones(n_samples)     # Always on
        repump_data = np.zeros(n_samples)   # Always off

        # Set the sequence parameters
        self.clock_rate = sample_rate
        self.output_data = {
            self.repump_id        : repump_data,
            self.probe_id         : probe_data,
            self.probe_id+'_freq' : probe_freq_data
        }
        self.input_samples = {
            self.counter_id : n_samples
        }
        self.readout_delays = {}    # No delays
        self.soft_start = {}        # No soft start
        self.timeout = n_samples / sample_rate + 1    # 1 extra second

        print('Starting probe scan...')

        # Set the laser to the start position
        self.set_probe_voltage_smooth(setpoint=voltage_min)
        self.set_probe_switch(setpoint=True)

        # Repump (doing a software timed repump since it doesn't really matter)
        if repump_time > 0:
            print(f'Starting repump for {repump_time:.3f} s...')
            self.set_probe_voltage(setpoint=voltage_min)
            self.set_repump_switch(True)
            time.sleep(repump_time)
            self.set_repump_switch(False)
            print('Repump completed.')

        # Run the scan
        print(f'Starting scan for {scan_time:.3f} s...')
        # Open the wavemeter
        self.wavemeter_controller.open()
        # Read the initial wavelength
        time_tag, probe_value_start = self.wavemeter_controller.readout()
        # Run the scan
        data = self._run_sequence(process_method=self.process_scan_data)
        # Read the final wavelength
        time_tag, probe_value_end = self.wavemeter_controller.readout()
        # Approximate vector of the frequencies
        freqs = np.linspace(probe_value_start,probe_value_end,n_pixels)
        # Close the wavemeter
        self.wavemeter_controller.close()
        # Record the final position
        self.probe_voltage = voltage_max
        print('Scan completed.')

        # Set the probe voltage depending on the optimization
        if optimize == 'max':
            # Get the max value in the scan range and center the laser on it
            max_idx = np.argmax(data)
            center_freq = freqs[max_idx]
            center_voltage = probe_freq_pixels[max_idx]
            # Set the voltage to the center value
            self.set_probe_voltage_smooth(center_voltage)
            # Set the target frequency reading to the center value
            self.set_probe_target(center_freq)
            # Report
            print(f'Setting probe to the max signal at {center_voltage:.2f} V and wavemeter reading {center_freq:.4f}')
        elif optimize == 'min':
            # Get the max value in the scan range and center the laser on it
            min_idx = np.argmin(data)
            center_freq = freqs[min_idx]
            center_voltage = probe_freq_pixels[min_idx]
            # Set the voltage to the center value
            self.set_probe_voltage_smooth(center_voltage)
            # Set the target frequency reading to the center value
            self.set_probe_target(center_freq)
            # Report
            print(f'Setting probe to the min signal at {center_voltage:.2f} V and wavemeter reading {center_freq:.4f}')
        elif optimize == 'min_offset':
            # Get the max value in the scan range and center the laser on it
            min_idx = np.argmin(data)
            center_freq = freqs[min_idx]
            center_voltage = probe_freq_pixels[min_idx]
            # Set the voltage to the center value
            self.set_probe_voltage_smooth(center_voltage)
            # Set the target frequency reading to the center value
            self.set_probe_target(center_freq + setpoint_offset)
            # Report
            print(f'Setting probe to the min signal with {setpoint_offset:.2f} offset at {center_voltage:.2f} V and wavemeter reading {center_freq:.4f}')
            center_freq = center_freq + setpoint_offset
        elif optimize == 'max_offset':
            # Get the max value in the scan range and center the laser on it
            max_idx = np.argmax(data)
            center_freq = freqs[max_idx]
            center_voltage = probe_freq_pixels[max_idx]
            # Set the voltage to the center value
            self.set_probe_voltage_smooth(center_voltage)
            # Set the target frequency reading to the center value
            self.set_probe_target(center_freq + setpoint_offset)
            # Report
            print(f'Setting probe to the max signal with {setpoint_offset:.2f} offset at {center_voltage:.2f} V and wavemeter reading {center_freq:.4f}')
            center_freq = center_freq + setpoint_offset
        elif optimize == 'min_offset_volt':
            # Get the max value in the scan range and center the laser on it
            min_idx = np.argmin(data)
            center_voltage = probe_freq_pixels[min_idx]
            # Set the voltage to the center value
            self.set_probe_voltage_smooth(center_voltage)
            # Read the current wavelength (assumes the voltage is more accurate than the wavemeter estimation)
            self.wavemeter_controller.open()
            time_tag, probe_target = self.wavemeter_controller.readout()
            self.wavemeter_controller.close()
            # Set the target frequency reading to the center value
            self.set_probe_target(probe_target + setpoint_offset)
            # Report
            print(f'(Using voltage) Setting probe to the min signal with {setpoint_offset:.2f} offset at {center_voltage:.2f} V and wavemeter reading {probe_target:.4f}')
            center_freq = probe_target + setpoint_offset
        elif optimize == 'max_offset_volt':
            # Get the max value in the scan range and center the laser on it
            max_idx = np.argmin(data)
            center_voltage = probe_freq_pixels[max_idx]
            # Set the voltage to the center value
            self.set_probe_voltage_smooth(center_voltage)
            # Read the current wavelength (assumes the voltage is more accurate than the wavemeter estimation)
            self.wavemeter_controller.open()
            time_tag, probe_target = self.wavemeter_controller.readout()
            self.wavemeter_controller.close()
            # Set the target frequency reading to the center value
            self.set_probe_target(probe_target + setpoint_offset)
            # Report
            print(f'(Using voltage) Setting probe to the max signal with {setpoint_offset:.2f} offset at {center_voltage:.2f} V and wavemeter reading {probe_target:.4f}')
            center_freq = probe_target + setpoint_offset
        else:
            # No optimization so return to the beginning
            self.set_probe_voltage_smooth(voltage_min)
            print(f'Setting probe to start voltage {voltage_min:.3f} V.')

        # Close both the repump and probe switches
        self.set_repump_switch(False)
        self.set_probe_switch(True)     # Hold true to mitigate issue with the AOM charging time

        # Record the data internally
        self.single_probe_scan_freq = freqs
        self.single_probe_scan_volt = probe_freq_pixels
        self.single_probe_scan_data = data

        # Plot the results
        fig, ax = plt.subplots(1,1,figsize=(5,4))
        ax.plot(freqs, data)
        if optimize is not None:
            ax.axvline(center_freq, color='k', alpha=0.5)
        ax.set_xticks(np.linspace(freqs[0], freqs[-1], 5))
        ax.set_xlabel('Wavemeter reading (GHz or nm)')
        ax.set_ylabel('Signal (cts/s)')
        ax.grid(alpha=0.3)
        plt.show()

        print('Finished probe scan.')

    def set_repump_switch(
            self,
            setpoint: bool = True
    ):
        '''
        Set the repump laser switch on or off.
        '''
        self.set_output(output_id=self.repump_id, setpoint=setpoint)

    def set_probe_switch(
            self,
            setpoint: bool = True
    ):
        '''
        Set the probe laser switch on or off.
        '''
        self.set_output(output_id=self.probe_id, setpoint=setpoint)

    def stabilize(
            self,
            tol: float = 0.5,
            hold_window: float = 5,
            max_attempts: float = 50,
            query_period: float = 0.25,
            freq_volt_grad: float = -24,
            penalty: float = 0.95,
            probe_on: bool = False
    ):
        '''
        Parameters
        ----------
        tol: float = 0.1
            Tolerance within which the wavemeter reading must remain.
        hold_window: float = 5
            Number of measurements to hold the value within tollerance of the optimum to succeed.
        max_attempts: float = 50
            The maximum number of attempts to stabilize the laser before erroring out.
        query_period: float = 0.1
            Minimum amount of time betwen successive queries of the wavemeter.
        freq_volt_grad: float = -24
            Approximate gradient of the wavemeter reading versus voltage curve. Default value is -24
            GHz/V. 
        penalty: float = 0.95
            Factor by which the assumed gradient is diminished after each optimization attempt.
            This ensures that the stabilizer converges to some value in the limit of infinite
            attempts. However it is not guaranteed that it converges to the desired value if it
            cannot get close enough in time. Pentalties closer to 1 increase the probability of
            converging to the desired value at the expense of taking longer on average. Smaller
            penalty values increase the convergence rate but decrease the likelyhood of reaching the
            desired value.
        '''
        print(f'Stabilizing the laser at {self.probe_target:.4f}.')

        if probe_on:
            self.set_probe_switch(True)
        else:
            self.set_probe_switch(False)

        # Open the wavemeter
        self.wavemeter_controller.open()

        errors = []
        current_penalty = 1
        for i in range(max_attempts):

            try:
                # Save the current reading
                time_tag, reading = self.wavemeter_controller.readout()
                # Compute the error
                error = self.probe_target - reading
                # Save the error
                errors.append( error )
                print(f'Target = {self.probe_target:.4f}, Actual = {reading:.4f}, error = {error:.4f}.')
                # Check if success condition achieved
                if i > hold_window and all(abs(e) < tol for e in errors[-hold_window:]):
                    print('Laser converged to desired value.')
                    # Close the wavemeter
                    self.wavemeter_controller.close()
                    return None
                # Else if in tollerance then do not adjust and continue
                elif abs(error) < tol:
                    print('Laser in tollerance')
                    # Wait for the query period before next attempt
                    time.sleep(query_period)
                # Otherwise continue...
                else:
                    # Compute the step size
                    dvoltage = current_penalty * error / freq_volt_grad
                    # Adjust the voltage
                    self.set_probe_voltage_smooth(self.probe_voltage+dvoltage)
                    # Increase the penalty
                    current_penalty = current_penalty * penalty
                    # Wait for the query period before next attempt
                    time.sleep(query_period)
            except Exception as e:
                # Catch read errors
                print('Error caught:', e)
                time.sleep(query_period)
        # Close the wavemeter
        self.wavemeter_controller.close()
        # Throw error if reached this point without converging
        raise RuntimeError('Failed to stablize at target value within allotted attempts.')

    def get_sequence_output_data(
            self,
            **kwargs
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
        **kwargs
            Keyword arguments defining the sequence parameters.
        '''
        raise NotImplementedError('Subclasses must implement this method.')

    def run(
            self,
            n_batches: int,
            n_repetitions: int,
            clock_rate: float=100000,
            scan_kwargs: dict = None,
            stabilization_kwargs: dict = None,
            save_fname: str = None,
            **kwargs
    ):
        '''
        Runs `n_batches` of the pulse sequence with each batch containing `n_repetitions` of the 
        single sequence (e.g. one repump and one probe pulse) sequence. Before each batch the probe 
        laser is stabilized and after each batch the data is displayed to the figure. If parameters
        are provided, also can run a single scan between batches to update the desired laser
        frequency value.

        Parameters
        ----------
        n_batches: int
            Number of batches to perform.
        n_repetitions: int
            Number of pulse sequence repetitions to perform per batch.
        clock_rate: float=100000
            Sample clock rate for writing and reading data. Default value is 1e5. Note that the
            current implementation is limited by the analog-digital-conversion of the analog output
            signal to around 8e5 samples/second. In principle we can go above 1e6 if we remove the
            analog output probe control, but this would complicate things quite a bit so we neglect
            it for now. The maximum resolution is 1/8e5 Hz = 1.25 us.
        scan_kwargs: dict = None
            Dictionary of keyword argument and value pairs for a scan to be prepared between
            sequences. If None then the scan is not performed.
        stabilization_kwargs: dict = None
            Dictionary of keyword argument and value pairs for the stabilization method. If None the
            default values are used.
        save_fname: str = None
            If provided, saves the data from this run to the provided file name (adding a '.hdf5'
            extension). May include the directory.
        **kwargs
            Keyword arguments to the `self.get_sequence_output_data` method which computes the
            output datastreams.
        '''
        # Save parameters
        self.n_batches = n_batches
        self.n_repetitions = n_repetitions
        self.clock_rate = clock_rate

        # Calculate the sequence output data save to the class instance attributes
        self.get_sequence_output_data(**kwargs)

        # Set the sequence parameters
        self.single_sequence_time = np.arange(self.single_sequence_n_samples) / clock_rate
        n_samples = self.n_repetitions * self.single_sequence_n_samples
        self.output_data = {
            self.repump_id        : np.tile(self.single_sequence_repump_data, self.n_repetitions), # Repeats sequence
            self.probe_id         : np.tile(self.single_sequence_probe_data, self.n_repetitions),
            self.probe_id+'_freq' : None # Add this after stabiliztaion
        }
        self.input_samples = {
            self.counter_id : n_samples
        }
        self.readout_delays = {}    # No delays
        self.soft_start = {}        # No soft start
        self.timeout = n_samples / clock_rate + 1    # 1 extra second

        print('Starting the sequence...')
        # Clear old data
        self.data_batches = []
        self.batch_probe_targets = []

        # Configure the plot for live display
        fig, ax = plt.subplots(1,1,figsize=(5,4))
        ax.set_xlabel('time (s)')
        ax.set_ylabel('batch-avg signal (cts/s)')
        ax.set_title('Completed batches: 0')
        plt.show()

        # Loop for the specified number of batches
        for k in range(n_batches):
            # Run a scan to start and determine the target frequency if desired
            if scan_kwargs is not None:
                # Run the single scan
                self.single_probe_scan(**scan_kwargs)
                # Reset the sequence parameters
                self.clock_rate = clock_rate
                self.output_data = {
                    self.repump_id        : np.tile(self.single_sequence_repump_data, self.n_repetitions), # Repeats sequence
                    self.probe_id         : np.tile(self.single_sequence_probe_data, self.n_repetitions),
                    self.probe_id+'_freq' : None # Add this after stabiliztaion
                }
                self.input_samples = {
                    self.counter_id : n_samples
                }
                self.readout_delays = {}    # No delays
                self.soft_start = {}        # No soft start
                self.timeout = n_samples / self.clock_rate + 1    # 1 extra second

            # Stablize the laser
            if stabilization_kwargs is None:
                stabilization_kwargs = {}
            self.stabilize(**stabilization_kwargs)
            # Record the probe target value
            self.batch_probe_targets.append(self.probe_target)
            # Write the stabilized voltage to the output
            self.output_data[self.probe_id+'_freq'] = np.ones(n_samples) * self.probe_voltage
            # Run a single sequence
            data = self._run_sequence(process_method=self.process_sequence_data)
            # Store the batched data 
            self.data_batches.append(data)
            # Average the data
            averaged_data = np.average(data, axis=0)

            # Update the plot
            ax.plot(self.single_sequence_time,averaged_data)
            ax.set_title(f'Completed batches: {k+1}')
            display.display(fig)

        if save_fname is not None:
            self.save(filename=save_fname)

        print('Finished.')

    def process_sequence_data(
            self,
            data: dict[str,np.ndarray]
    ) -> np.ndarray:
        '''
        Processes the sequence data.

        Converts the super-sequence of `n_repetitions` of the single pulse sequence into an array
        where each row is one of the repetitions.
        '''
        # Get the data for the spcm
        output_data = data[self.counter_id]
        # Get the samples per sequence
        n_samples_sequence = int(len(output_data) / self.n_repetitions)
        # Reshape to array and return
        return np.reshape(output_data,(self.n_repetitions,n_samples_sequence))

    def process_scan_data(
            self,
            data: dict[str,np.ndarray]
    ) -> np.ndarray:
        '''
        Process the scan data.

        Extracts the spcm data and compresses the subpixels.
        '''
        # Get the data for the spcm
        output_data = data[self.counter_id]
        # Get the number of pixels
        n_pixels = int(len(output_data) / 16)    # 16 subpixels
        # Get the reshaped data
        output_data = np.reshape(output_data, (n_pixels, 16))
        # Average and return
        return np.average(output_data, axis=1).squeeze()

    def save(
            self,
            filename: str
    ):
        '''
        Saves the current sequence settings and data to an hdf5 file with the given `filename`.
        '''
        # Add the extension
        fname = filename+'.hdf5'

        # Check if a file with the same name already exists, add counter if it does
        k = 0
        while os.path.isfile(fname):
            print(f'File `{fname}` already exists.')
            fname = filename + '-'+str(k)+'.hdf5'
            k += 1

        # Save as hdf5
        print(f'Saving data as `{fname}`.')
        with h5py.File(fname, 'w') as f:

            # Save the scan settings
            # Run through the scan parameters dictionary saving data 
            ds = f.create_dataset('sequence_settings', data=np.array([]))
            for param, val in self.sequence_settings.items():
                ds.attrs[param] =  val

            # Save the data for a single sequence
            f.create_dataset('single_sequence_time', data=self.single_sequence_time)
            f.create_dataset('single_sequence_repump', data=self.single_sequence_repump_data)
            f.create_dataset('single_sequence_probe', data=self.single_sequence_probe_data)

            # Save the raw data of the repeated super sequence. A three dimensional array with the
            # first index being each batch, second being each repetition, and third being each
            # sample. Using float32 instead of default 64 to reduce the dataset size.
            f.create_dataset('samples', data=np.array(self.data_batches, dtype=np.float32))
            f.create_dataset('target_freqs', data=np.array(self.batch_probe_targets))

            # Save data for the last scan for finding the resonance
            f.create_dataset('scan_freqs', data=np.array(self.single_probe_scan_freq))
            f.create_dataset('scan_volts', data=np.array(self.single_probe_scan_volt))
            f.create_dataset('scan_signal', data=np.array(self.single_probe_scan_data))
            # Save the last target frequency
            f.create_dataset('target_freq', data=np.array([self.probe_target,]))

        print('File saved.')

    def get_max_dit_contrast(
            self,
            cavity_wavelength,
            kappa=115,
            gamma=0.15,
            Delta = 0,
            g = 2,
            splitting=0.1
    ):
        '''
        Gets the index corresponding to the frequency/voltage that maximizes the contrast of the
        DIT signal for a drop port signal.
        '''
        # Estimate cavity center frequency from known cavity wavelength
        omega0 = 299792458 / cavity_wavelength # C[nm GHz] / wavelength[nm]
        print(f'Cavity center frequency {omega0:.1f}')
        # Data
        xfit = self.single_probe_scan_freq - omega0
        yfit = self.single_probe_scan_data

        # Define the model (needs to be dynamically created to set kappa,gamma)
        def split_drop_dit(
                delta,
                Delta,
                g,
                splitting,
                c0,
                c1
        ):
            peak1 = self._single_drop_dit(delta, Delta=Delta-splitting/2, g=g, kappa=kappa, gamma=gamma)
            peak2 = self._single_drop_dit(delta, Delta=Delta+splitting/2, g=g, kappa=kappa, gamma=gamma)
            signal = (peak1 + peak2)/2 
            return signal * (c0 + c1*(delta-Delta))

        # Parameter estimates
        p0 = [Delta, g, splitting, np.average(yfit), 0]
        # Fit
        p, c = curve_fit(
            f=split_drop_dit,
            xdata=xfit,
            ydata=yfit,
            p0=p0,
            bounds=[ [-np.inf, 0, 0, 0, -np.inf], [np.inf,]*5 ]
        )

        # Determine the contributions
        Delta, g, splitting, c0, c1 = p
        peak1 = self._single_drop_dit(xfit, Delta=Delta-splitting/2, g=g, kappa=kappa, gamma=gamma)
        peak2 = self._single_drop_dit(xfit, Delta=Delta+splitting/2, g=g, kappa=kappa, gamma=gamma)
        norm = self._single_drop_dit(xfit, Delta=Delta, g=0, kappa=kappa, gamma=gamma)
        contrast = np.abs(peak1 - peak2) / norm

        # Get the frequency and voltage of the maximum
        max_idx = np.argmax(contrast)
        target_freq = self.single_probe_scan_freq[max_idx]
        target_volt = self.single_probe_scan_volt[max_idx]
        # Set the voltage to the center value
        self.set_probe_voltage_smooth(target_volt)
        # Set the target frequency reading to the center value
        self.set_probe_target(target_freq)

        # Plot the results
        fig, ax = plt.subplots(figsize=(4,3))
        ax.plot(xfit, yfit, 'o')
        ax.plot(xfit, split_drop_dit(xfit, *p), 'k-')
        ax.set_xlabel('frequency (GHz)')
        ax.set_ylabel('signal')
        plt.show()

    def _single_drop_dit(
            self,
            delta,
            Delta,
            g,
            kappa,
            gamma
    ):
        '''
        Gets the single SiV DIT signal as a function of the cavity detuning delta.
        '''
        kappa = kappa
        gamma = gamma
        num = kappa * (1j*(delta-Delta) + gamma/2)
        den = (1j*(delta-Delta) + gamma/2) * (1j*delta + kappa/2) + g*g
        return np.abs(num/den)**2
    
    def _split_drop_dit(
            self,
            delta,
            Delta,
            g,
            splitting,
            c0,
            c1
    ):
        '''
        Gets a split DIT signal with linear background
        '''
        peak1 = self._single_drop_dit(delta, Delta-splitting/2, g)
        peak2 = self._single_drop_dit(delta, Delta+splitting/2, g)
        signal = (peak1 + peak2)/2 
        return signal * (c0 + c1*(delta-Delta))





