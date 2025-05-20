import nidaqmx
import nidaqmx.constants
import nidaqmx.errors
import nidaqmx.stream_readers
import nidaqmx.stream_writers

import numpy as np
import matplotlib.pyplot as plt

'''
In this case we generate the clock signal on the counter output and route that signal to use as the
clock timing source for the rest of the system.
'''

def main():
    
    ao_device_channel = 'Dev1/ao0'
    ai_device_channel = 'Dev1/ai1'
    ci_device_channel = 'Dev1/ctr2'
    ci_terminal = 'PFI0'
    clock_dev = 'Dev1'
    clock_channel = 'ctr0'
    clock_terminal = 'PFI12'

    n_samples = 100
    sample_rate = 10

    data = np.cos(np.linspace(0,2*np.pi, n_samples))

    with (
        nidaqmx.Task() as clock_task,
        nidaqmx.Task() as ao_task,
        nidaqmx.Task() as ai_task,
        nidaqmx.Task() as ci_task,
    ):
        # Create counter output channel for the clock
        clock_channel = clock_task.co_channels.add_co_pulse_chan_freq(
            counter=clock_dev + '/' + clock_channel,
            freq = sample_rate,
            idle_state=nidaqmx.constants.Level.LOW,
            initial_delay=3, # Delay 1 s
        )
        clock_channel.co_pulse_term = '/'+clock_dev+'/'+clock_terminal

        clock_task.timing.cfg_implicit_timing(sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS)
        clock_task.control(nidaqmx.constants.TaskMode.TASK_COMMIT)

        # Create the AO voltage channel and configure the timing
        ao_task.ao_channels.add_ao_voltage_chan(ao_device_channel)
        ao_task.timing.cfg_samp_clk_timing(
            sample_rate,
            source='/'+clock_dev+'/PFI12',
            sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
            samps_per_chan=n_samples
        )
        # Configure the trigger for the AO task
        # ao_task.triggers.start_trigger.cfg_dig_edge_start_trig(
        #     trigger_source='/'+clock_dev+'/Ctr0StartArmTrigger'
        # )
        

        # Create the AI voltage channel and configure the timing
        ai_task.ai_channels.add_ai_voltage_chan(ai_device_channel)
        ai_task.timing.cfg_samp_clk_timing(
            sample_rate,
            source='/'+clock_dev+'/PFI12',
            sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
            samps_per_chan=n_samples
        )
        # Configure the trigger for the AI task
        # ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(
        #     trigger_source='/'+clock_dev+'/Ctr0StartArmTrigger'
        # )

        # Create the counter input channel
        ci_channel = ci_task.ci_channels.add_ci_count_edges_chan(
            ci_device_channel,
            initial_count=0,
            count_direction=nidaqmx.constants.CountDirection.COUNT_UP,
            edge=nidaqmx.constants.Edge.RISING
        )
        # Configure the terminal for the signal to count
        ci_channel.ci_count_edges_term = '/Dev1/' + ci_terminal
        # Configure the timing
        ci_task.timing.cfg_samp_clk_timing(
            sample_rate,
            source='/'+clock_dev+'/PFI12',
            active_edge=nidaqmx.constants.Edge.RISING,
            sample_mode=nidaqmx.constants.AcquisitionType.FINITE,
            samps_per_chan=n_samples
        )
        # Arm the start trigger
        # ci_task.triggers.arm_start_trigger.trig_type = nidaqmx.constants.TriggerType.DIGITAL_EDGE
        # ci_task.triggers.arm_start_trigger.dig_edge_edge = nidaqmx.constants.Edge.RISING
        # ci_task.triggers.arm_start_trigger.dig_edge_src ='/'+clock_dev+'/Ctr0StartArmTrigger'
        # Set the counter buffer size
        ci_task.in_stream.input_buf_size = n_samples

        # Write the data to the AO channel
        ao_task.write(data)

        # Prepare the counter reader for the ci_task
        ci_reader = nidaqmx.stream_readers.CounterReader(ci_task.in_stream)

        print('Starting tasks')
        # Start the AO task, will wait until the start of the clock task to begin
        ao_task.start()
        # Start the AI task, will wait until the start of the clock tast to begin
        ai_task.start()
        # Start the CI task, will wait until the start of the clock task to begin
        ci_task.start()
        # Start the clock task
        clock_task.start()

        print('Waiting until done')
        # Wait until done
        ao_task.wait_until_done(timeout=60) # 10 second buffer
        ai_task.wait_until_done(timeout=60) # 10 second buffer
        ci_task.wait_until_done(timeout=60) # 10 second buffer

        print('Getting data')
        # Get the counter data via the I/O stream
        data_buffer = np.zeros(n_samples,dtype=np.uint32)
        ci_reader.read_many_sample_uint32(
            data_buffer,
            number_of_samples_per_channel=n_samples
        )

        # Get the AI data
        ai_data = ai_task.read(number_of_samples_per_channel=n_samples)

        # Stop the tasks
        clock_task.stop()
        ci_task.stop()
        ai_task.stop()
        ao_task.stop()

        print('DONE!')

    plt.plot(data)
    plt.plot(ai_data, '--')
    plt.show()


if __name__ == '__main__':
    main()