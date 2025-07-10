import numpy as np
import matplotlib.pyplot as plt
import time

import nidaqmx
import nidaqmx.constants
import nidaqmx.stream_readers
import nidaqmx.stream_writers

'''
This is a simple example script for simultaneously reading and writing multiple AO/AI channels on
the same DAQ simultaneously.


Notes
-----
In general, multichannel tasks require that channels and clocks are on the same device (e.g. "Dev1")
to work properly. This includes the routing of the start trigger from the clock task. Consequently,
the hardware connected to any given DAQ device will (by default) operate independently from other
devices.

In situations where more than one device is required, it is possible to link two devices. To do so
one must:
    (1) Physically link the DAQ devices by an RTSI cable bus see the following for more details:
        https://www.ni.com/en/support/documentation/supplemental/18/real-time-system-integration--rtsi--and-configuration-explained.html
    (2) In the NI MAX desktop application, locate the dropdown menu for the "Devices and Interfaces"
        in the nagivation tree (your DAQ devices should both be visible, e.g. "NI PCIe-6323 'Dev1'"
        and "NI PCIe-6323 'Dev2'"). Then right click on "Devices and Interfaces" and select "Add
        new". This opens a dialog window from which you can select "NI RSTI cable".
    (3) Right click on the new "NI RSTI cable" in the device manager to add your DAQ devices to it.

Once this is done you should be able to run the following script (and any of the derivative scripts)
with any arbitrary combination of devices and channels. This works via the "channel expansion"
implemented by `nidaqmx`.

If you have not told the DAQ about the RTSI cable then `nidaqmx` will throw an error saying as much.
The more pernicious case is when the cable is missing or not connected correctly. In such instances
the software will either: (1) throw an error indicating it was unable to route the signal(s) to the
requested terminals, or (2) it will run but the start trigger and/or clock may not reach the device
(if it is on the other device) and so the task will not trigger or run until it eventually times out
or the user stops the script manually.
'''


def main(): 

    # Device/channels for i/o and clock
    clock_dev_ch = ('Dev1', 'port0')
    clock_term = 'PFI0'
    ao_dev_ch_1 = ('Dev1', 'ao0')
    ao_dev_ch_2 = ('Dev1', 'ao1')
    ai_dev_ch_1 = ('Dev1', 'ai1')
    ai_dev_ch_2 = ('Dev1', 'ai2')

    # Sample rate
    sample_rate = 32

    # Readout delay
    readout_delay = 2

    # Data to write
    n_samples = 128
    x = np.linspace(0,1,n_samples)
    ao_data_1 = np.cos(2*np.pi*x)
    ao_data_2 = np.sin(2*np.pi*x)
    

    with nidaqmx.Task() as ao_task, nidaqmx.Task() as ai_task, nidaqmx.Task() as clock_task:
          
        # Create virtual DI clock task on an internal channel
        clock_task.di_channels.add_di_chan(clock_dev_ch[0]+'/'+clock_dev_ch[1])
        clock_task.timing.cfg_samp_clk_timing(
            sample_rate,
            sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS
        )
        # Commit the clock task to hardware
        clock_task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)


        # Write multiple AO channels to the ao task
        ao_task.ao_channels.add_ao_voltage_chan(ao_dev_ch_1[0]+'/'+ao_dev_ch_1[1])
        ao_task.ao_channels.add_ao_voltage_chan(ao_dev_ch_2[0]+'/'+ao_dev_ch_2[1])
        # Configure the timing on the AO task to operate for as many samples as there are data
        # points in the provided data vector. Running on the finite sample mode ensures that
        # only the voltage samples provided in the data vector are written.
        ao_task.timing.cfg_samp_clk_timing(
            sample_rate,
            source='/'+clock_dev_ch[0]+'/di/SampleClock',
            sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
            samps_per_chan=n_samples
        )
        # Set the start trigger to be the start trigger of the ai_task
        ao_task.triggers.start_trigger.cfg_dig_edge_start_trig('/'+clock_dev_ch[0]+'/di/StartTrigger')

        # Write the data to the channel
        # The data should be a 2-d array with rows corresponding to the channels in the order they
        # were defined.
        ao_data = np.array([ao_data_1,ao_data_2])
        writer = nidaqmx.stream_writers.AnalogMultiChannelWriter(ao_task.out_stream)
        writer.write_many_sample(data=ao_data, timeout=n_samples/sample_rate + 1)


        # Write multiple AI channels to the ai task
        ai_task.ai_channels.add_ai_voltage_chan(ai_dev_ch_1[0]+'/'+ai_dev_ch_1[1])
        ai_task.ai_channels.add_ai_voltage_chan(ai_dev_ch_2[0]+'/'+ai_dev_ch_2[1])
        # Configure the timing on the AO task to operate for as many samples as there are data
        # points to read out.
        ai_task.timing.cfg_samp_clk_timing(
            sample_rate,
            source='/'+clock_dev_ch[0]+'/di/SampleClock',
            sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
            samps_per_chan=n_samples+readout_delay
        )
        # Set the start trigger to be the start trigger of the ai_task
        ai_task.triggers.start_trigger.cfg_dig_edge_start_trig('/'+clock_dev_ch[0]+'/di/StartTrigger')

        # Prepare the reader to read the data after the task aquisition
        reader = nidaqmx.stream_readers.AnalogMultiChannelReader(ai_task.in_stream)
        
        # Start the AO task, will wait until the start of the clock task to begin
        ao_task.start()
        # Start the AI task, will wait until the start of the clock tast to begin
        ai_task.start()
        # Start the clock task, triggers the rest to start
        clock_task.start()

        # Wait until done
        print('Waiting for tasks to finish...')
        ao_task.wait_until_done(timeout=n_samples*sample_rate + 1) # 1 second buffer
        print('Done.')

        # Get the output data
        ai_data = np.zeros(shape=(2,n_samples+readout_delay))
        reader.read_many_sample(data=ai_data,
                                number_of_samples_per_channel=n_samples+readout_delay,
                                timeout=n_samples/sample_rate + 1)

        # Plot the results
        fig, ax = plt.subplots(2,1,sharex=True)
        ax[0].plot(x,ao_data_1)
        ax[0].plot(x,ai_data[0,readout_delay:], '--')
        ax[1].plot(x,ao_data_2)
        ax[1].plot(x,ai_data[1,readout_delay:], '--')
        plt.show()
        




if __name__ == '__main__':
    main()