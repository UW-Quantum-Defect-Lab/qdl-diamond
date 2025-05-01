import numpy as np
import matplotlib.pyplot as plt
import time

from qdlutils.hardware.nidaq.synchronous.sequence_ao_ai_ci import SequenceAOVoltageAIVoltageCIEdge

'''
This file runs an example usage of the synchronous AO-CI class.

Note, as with the AO-AI class, the execution time reported in this script will be slightly larger
than the expected time. This is primarily due to the overhead of preparing the hardware and starting
the tasks.

This implementation also uses the standard edge counter and so one should be aware of any issues 
with the counter rollover at 2**32 detections. However, this should have minimal impact for most
use cases. Processing with `np.unwrap` should be able to correct for this if not, but the general
philosophy here is that the user/developer should handle this at the higher level.
'''

def main():

    # Create an experiment for synchronous AO/AI voltage signals.
    exp = SequenceAOVoltageAIVoltageCIEdge(
        ao_device = 'Dev1',
        ao_channel = 'ao0',
        ai_device = 'Dev1',
        ai_channel = 'ai1',
        ci_device = 'Dev1',
        ci_channel = 'ctr2',
        ci_terminal = 'PFI0',
        ao_min_voltage = -5.0,
        ao_max_voltage = 5.0,
    )

    ''# Number of samples in the sequence
    n_samples = 256

    # Rate of samples per second
    sample_rate = 256

    # Generate the data
    data_x = np.arange(0,n_samples) / sample_rate
    data_y = np.sin(data_x * 2 * np.pi)

    # Optionally set the starting voltage to test the soft start
    exp.set_voltage(2)

    # Run the sequence and time it externally
    start_time = time.time()
    exp.run_sequence(
        data = data_y,
        sample_rate=sample_rate,
        soft_start=True,
        readout_delay=1
    )
    end_time = time.time()

    # Output
    print(f'Time elapsed during sequence execution = {end_time-start_time:.3f} s')
    print(f'Expected time for sequence = {n_samples/sample_rate:.3f} s')

    # Compute the count rate
    count_rate = np.diff(exp.ci_data, prepend=0) * sample_rate

    # Plot the results
    fig, ax = plt.subplots(2,1, sharex=True)
    ax[0].plot(data_x, exp.ao_data, 'k--', label='AO data')
    ax[0].plot(data_x, exp.ai_data, 'o', markersize=2, label='AI data')
    ax[1].plot(data_x, count_rate, label='count rate')
    ax[0].legend(frameon=False)
    ax[1].set_xlabel('Time (s)')
    ax[0].set_ylabel('Voltage (V)')
    ax[0].set_ylabel('Count rate (cts/s)')
    plt.show()



if __name__ == '__main__':
    main()


