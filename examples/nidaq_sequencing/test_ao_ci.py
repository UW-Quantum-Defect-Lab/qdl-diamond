import numpy as np
import matplotlib.pyplot as plt
import time

from qdlutils.hardware.nidaq.synchronous.sequence_ao_ci import SequenceAOVoltageCIEdge


'''
This file runs an example usage of the synchronous AO-CI class.

Note, as with the AO-AI class, the execution time reported in this script will be slightly larger
than the expected time. This is primarily due to the overhead of preparing the hardware and starting
the tasks.

Be aware that the current implementation utilizes the standard edge counter which reports the number
of edge detection events since the start of the task. This means that the `exp.data` property is an
`np.ndarray` with length `n_samples = len(data)` consisting of strictly non-decreasing integers.
Each entry reports the number of counts obtained at that particular sample since the beginning of
of the task. To extract the counts per sample and the count rate utilize the following

    ```
        counts_per_sample = np.diff(exp.data, prepend=0) # Calculates diff from 0
        count_rate = counts_per_sample * sample_rate
    ```

Note that this has the strict hardware limit of the 32-bit counter. Consequently, if the total 
counts ever rolls over 2**32 ~ 4e9 then the data values will roll over resulting in a large negative
count rate on that particular sample.

However this is unlikely to happen in any experiment as it would correspond to a 1 MHz signal
running continuously for about 15 minutes. If this is problematic for any particular application,
one can utilize the `np.unwrap` method to correct this.
'''

def main():

    # Create an experiment for synchronous AO/AI voltage signals.
    exp = SequenceAOVoltageCIEdge(
        ao_device = 'Dev1',
        ao_channel = 'ao0',
        ci_device = 'Dev1',
        ci_channel = 'ctr2',
        ci_terminal = 'PFI0',
        ao_min_voltage = -5.0,
        ao_max_voltage = 5.0,
    )

    ''# Number of samples in the sequence
    n_samples = 128

    # Rate of samples per second
    sample_rate = 64

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
        readout_delay=0
    )
    end_time = time.time()

    # Output
    print(f'Time elapsed during sequence execution = {end_time-start_time:.3f} s')
    print(f'Expected time for sequence = {n_samples/sample_rate:.3f} s')

    # Compute the count rate
    count_rate = np.diff(exp.ci_data, prepend=0) * sample_rate

    # Plot the results
    plt.plot(data_x, count_rate, label='count rate')
    plt.xlabel('TIme (s)')
    plt.ylabel('Count rate (cts/s)')
    plt.show()



if __name__ == '__main__':
    main()
