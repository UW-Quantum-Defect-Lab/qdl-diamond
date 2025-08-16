import logging
import numpy as np
import matplotlib.pyplot as plt
import time
import h5py

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

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class SimpleStateMonitoringExperiment(SequenceControllerBase):

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
        # Save supplied parameters not used in the parent class
        self.repump_id = repump_id
        self.probe_id = probe_id
        self.counter_id =counter_id
        # Wavemeter controller class for interfacing with the wavemeter
        self.wavemeter_controller = wavemeter_controller

        # Attributes for later use
        self.probe_target = None        # Target wavemeter reading to hold the laser at
        self.probe_voltage = None       # Voltage corresponding to the last setpoint
        self.sequence_settings = None   # Dictionary of the settings used in the sequence
        self.data_batches = []          # Data array. Each element in list is a batch, each batch is
                                        # a 2-d array with rows corresponding to a single subsequence.
    
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

    def single_probe_scan(
            self,
            voltage_min: float,
            voltage_max: float,
            n_pixels: int,
            scan_time: float,
            repump_time: float,
            optimize: str = None,
    ):
        '''
        Configures and performs a single probe laser sweep to assist in locating the resonance
        features of interest.
        For simplicity the sweep scans from the `voltage_min` to `voltage_max` only.

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
            Dictates if and how the probe frequency should be optimized. Options are `'min'` or 
            `'max'` which attempts to place the probe frequency at the min or max of the scan
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

        # Repump (doing a software timed repump since it doesn't really matter)
        if repump_time > 0:
            print(f'Starting repump for {repump_time:.3f} s...')
            self.set_probe_switch(False)
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
        print('Scan completed.')

        # Set the probe voltage depending on the optimization
        if optimize == 'max':
            # Looking for a peak so optimize on the center of mass
            center_freq = np.sum(freqs * data) / np.sum(data)
            center_voltage = np.sum(probe_freq_pixels * data) / np.sum(data)
            # Set the voltage to the center value
            self.set_probe_voltage(center_voltage)
            # Set the target frequency reading to the center value
            self.set_probe_target(center_freq)
            # Report
            print(f'Setting probe to center of mass at {center_voltage:.2f} V and wavemeter reading {center_freq:.4f}')
        elif optimize == 'min':
            # Looking for a dip so optimize on the inverse center of mass
            center_freq = np.sum(freqs / data) / np.sum(1/data)
            center_voltage = np.sum(probe_freq_pixels / data) / np.sum(1/data)
            # Set the voltage to the center value
            self.set_probe_voltage(center_voltage)
            # Set the target frequency reading to the center value
            self.set_probe_target(center_freq)
            print(f'Setting probe to center of inverse mass at {center_voltage:.2f} V and wavemeter reading {center_freq:.4f}')
        else:
            # No optimization so return to the beginning
            self.set_probe_voltage(voltage_min)
            print(f'Setting probe to start voltage {voltage_min:.3f} V.')

        # Close both the repump and probe switches
        self.set_repump_switch(False)
        self.set_probe_switch(False)    

        # Plot the results
        fig, ax = plt.subplots(1,1,figsize=(5,4))
        ax.plot(freqs, data)
        if optimize is not None:
            ax.axvline(center_freq, color='k', alpha=0.5)
        ax.set_xticks(np.linspace(freqs[0], freqs[-1], 5))
        ax.set_xlabel('Wavemeter reading (GHz or nm)')
        ax.set_ylabel('Signal (cts/s)')
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
            penalty: float = 0.95
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
                # Otherwise continue...
                else:
                    # Compute the step size
                    dvoltage = current_penalty * error / freq_volt_grad
                    # Adjust the voltage
                    self.set_probe_voltage(self.probe_voltage+dvoltage)
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

    def run(
            self,
            n_batches: int,
            n_repetitions: int,
            repump_time: float,
            probe_delay: float,
            probe_time: float,
            end_delay: float,
            clock_rate: float=100000,
            scan_kwargs: dict = None,
            stabilization_kwargs: dict = None,
    ):
        '''
        Runs `n_batches` of the state monitoring-pulse sequence with each batch containing
        `n_repetitions` of the single repump-probe sequence. Before each batch the probe laser is
        stabilized and after each batch the data is displayed.

        Parameters
        ----------
        n_batches: int
            Number of batches to perform.
        n_repetitions: int
            Number of pulse sequence repetitions to perform per batch.
        repump_time: float
            Repump time for the sequence in seconds.
        probe_delay: float
            Delay between the end of the repump and start of the probe in seconds.
        probe_time: float
            Length of the probe time in seconds.
        end_delay: float
            Delay at after the probe ends before the next repetition begins in seconds.
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
        '''

        # Get the times associated to the relevant points in the sequence in terms of clock cycles
        idx1 = int(repump_time * clock_rate)
        idx2 = idx1 + int(probe_delay * clock_rate)
        idx3 = idx2 + int(probe_time * clock_rate)
        idx4 = idx3 + int(end_delay * clock_rate)       # Number of samples per individual sequence

        # Generate data for a single sequence
        single_sequence_time = np.arange(idx4) / clock_rate
        single_sequence_repump_data = np.zeros(idx4, dtype=np.int32)
        single_sequence_repump_data[0:idx1] = 1
        single_sequence_probe_data = np.zeros(idx4, dtype=np.int32)
        single_sequence_probe_data[idx2:idx3] = 1

        # Save the sequence parameters
        self.sequence_settings = {
            'n_batches': n_batches,
            'n_repetitions': n_repetitions,
            'repump_time': repump_time,
            'probe_delay': probe_delay,
            'probe_time': probe_time,
            'end_delay': end_delay,
            'clock_rate': clock_rate,
            'scan_kwargs': scan_kwargs,
            'stabilization_kwargs': stabilization_kwargs,
            'single_sequence_samples': idx4
        }

        # Set the sequence parameters
        n_samples = n_repetitions * idx4
        self.clock_rate = clock_rate
        self.output_data = {
            self.repump_id        : np.tile(single_sequence_repump_data, n_repetitions), # Repeats sequence
            self.probe_id         : np.tile(single_sequence_probe_data, n_repetitions),
            self.probe_id+'_freq' : None # Add this after stabiliztaion
        }
        self.input_samples = {
            self.counter_id : n_samples
        }
        self.readout_delays = {}    # No delays
        self.soft_start = {}        # No soft start
        self.timeout = n_samples / clock_rate + 1    # 1 extra second

        print('Starting the sequence...')

        # Configure the plot for live display
        fig, ax = plt.subplots(1,1,figsize=(5,4))
        ax.set_xlabel('time (s)')
        ax.set_ylabel('batch-avg signal (cts/s)')
        ax.set_title('Completed batches: 0')
        plt.show()

        # Loop for the specified number of batches
        for k in range(n_batches):
            # Run a scan to start and determine the target frequency
            if scan_kwargs is not None:
                # Run the single scan
                self.single_probe_scan(**scan_kwargs)
                # Reset the sequence parameters
                n_samples = n_repetitions * idx4
                self.clock_rate = clock_rate
                self.output_data = {
                    self.repump_id        : np.tile(single_sequence_repump_data, n_repetitions), # Repeats sequence
                    self.probe_id         : np.tile(single_sequence_probe_data, n_repetitions),
                    self.probe_id+'_freq' : None # Add this after stabiliztaion
                }
                self.input_samples = {
                    self.counter_id : n_samples
                }
                self.readout_delays = {}    # No delays
                self.soft_start = {}        # No soft start
                self.timeout = n_samples / clock_rate + 1    # 1 extra second

            # Stablize the laser
            if stabilization_kwargs is None:
                stabilization_kwargs = {}
            self.stabilize(**stabilization_kwargs)
            # Write the stabilized voltage to the output
            self.output_data[self.probe_id+'_freq'] = np.ones(n_samples) * self.probe_voltage
            # Run a single sequence
            data = self._run_sequence(process_method=self.process_sequence_data)
            # Store the batched data 
            self.data_batches.append(data)
            # Average the data
            averaged_data = np.average(data, axis=0)

            # Update the plot
            ax.plot(single_sequence_time,averaged_data)
            ax.set_title(f'Completed batches: {k+1}')
            display.display(fig)

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
        n_samples_sequence = int(len(output_data) / self.sequence_settings['n_repetitions'])
        # Reshape to array and return
        return np.reshape(output_data,(self.sequence_settings['n_repetitions'],n_samples_sequence))

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


