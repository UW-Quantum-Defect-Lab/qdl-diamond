import numpy as np
import matplotlib.pyplot as plt
import time

from qdlutils.hardware.nidaq.synchronous.ao_ai import AnalogOutputAnalogInput


'''
This file runs an example usage of the synchronous AO-AI class.

Some notes on the performance of the script:
    1.  While the readout of the "Time elapsed during sequence execution" is generally longer than
        the simple ''expected'' time of `n_samples / sample_rate`, you can rest assured that this
        the difference is a software overhead due to the setup and shutdown of the associated NIDAQ
        tasks. 
        If you time from the start of the `ao_task` (which triggers the start of the `ai_task`) 
        until the `ai_task` finishes (via the `ai_task.wait_until_done()` method), you should find
        that this matches the expected value (upto software delays).
    2.  If you directly connect the AO to the AI, you will observe that there is an apparent one 
        (or more at faster sample rates) sample delay in the AI readout compared to the target AO
        signal waveform. This is believed to be due to hardware limiations on the AI, which seems to
        be reading the previous sample's AO value. This behavior is expected. 
'''

def main():

    # Create an experiment for synchronous AO/AI voltage signals.
    exp = AnalogOutputAnalogInput(
        ao_device = 'Dev1',
        ao_channel = 'ao0',
        ai_device = 'Dev1',
        ai_channel = 'ai1',
        ao_min_voltage = -5.0,
        ao_max_voltage = 5.0,
        ai_min_voltage = -5.0,
        ai_max_voltage = 5.0
    )

    # Number of samples in the sequence
    n_samples = 256

    # Rate of samples per second
    sample_rate = 256

    # Generate the data
    data_x = np.linspace(0,1,n_samples)
    data_y = np.sin(data_x * 2 * np.pi)

    # Optionally set the starting voltage to test the soft start
    exp.set_voltage(2)

    # Run the sequence and time it externally
    start_time = time.time()
    exp.run_sequence(
        data = data_y,
        sample_rate=sample_rate,
        soft_start=True
    )
    end_time = time.time()

    # Output
    print(f'Time elapsed during sequence execution = {end_time-start_time:.3f} s')
    print(f'Expected time for sequence = {n_samples/sample_rate:.3f} s')

    # Plot the results
    plt.plot(np.arange(n_samples), data_y, 'k--', label='AO voltage')
    plt.plot(np.arange(n_samples), exp.data, label='AI voltage')
    plt.xlabel('Sample number')
    plt.ylabel('Voltage')
    plt.show()



if __name__ == '__main__':
    main()
