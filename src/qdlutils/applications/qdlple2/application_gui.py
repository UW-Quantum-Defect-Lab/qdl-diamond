import logging

import numpy as np
import matplotlib
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import matplotlib.pyplot as plt

import tkinter as tk

matplotlib.use('Agg')

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

class LauncherApplicationView:

    '''
    Launcher application GUI view, loads the control panel
    '''
    def __init__(self, main_window: tk.Tk) -> None:
        main_frame = tk.Frame(main_window)
        main_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=30, pady=30)

        self.control_panel = LauncherControlPanel(main_frame)

class LauncherControlPanel:

    def __init__(self, main_frame) -> None:

        # Define command frame for start/stop/save buttons
        command_frame = tk.Frame(main_frame)
        command_frame.pack(side=tk.TOP, padx=0, pady=0)
        # Add buttons and text
        row = 0
        tk.Label(command_frame, 
                 text="PLE scan control", 
                 font='Helvetica 14').grid(row=row, column=0, pady=[0,5], columnspan=2)
        row += 1
        self.start_button = tk.Button(command_frame, text="Start Scan", width=12)
        self.start_button.grid(row=row, column=0, columnspan=2)


        # Define settings frame to set all scan settings
        settings_frame = tk.Frame(main_frame)
        settings_frame.pack(side=tk.TOP, padx=0, pady=[10,0])
        # Min voltage
        row += 1
        tk.Label(settings_frame, text="Min voltage (V)").grid(row=row, column=0)
        self.voltage_start_entry = tk.Entry(settings_frame, width=10)
        self.voltage_start_entry.insert(0, -3)
        self.voltage_start_entry.grid(row=row, column=1)
        # Max voltage
        row += 1
        tk.Label(settings_frame, text="Max voltage (V)").grid(row=row, column=0)
        self.voltage_end_entry = tk.Entry(settings_frame, width=10)
        self.voltage_end_entry.insert(0, 5)
        self.voltage_end_entry.grid(row=row, column=1)
        # Number of pixels on upsweep
        row += 1
        tk.Label(settings_frame, text="# of pixels up").grid(row=row, column=0)
        self.num_pixels_up_entry = tk.Entry(settings_frame, width=10)
        self.num_pixels_up_entry.insert(0, 200)
        self.num_pixels_up_entry.grid(row=row, column=1)
        # Number of pixels on downsweep
        row += 1
        tk.Label(settings_frame, text="# of pixels down").grid(row=row, column=0)
        self.num_pixels_down_entry = tk.Entry(settings_frame, width=10)
        self.num_pixels_down_entry.insert(0, 10)
        self.num_pixels_down_entry.grid(row=row, column=1)
        # Number of scans
        row += 1
        tk.Label(settings_frame, text="# of scans").grid(row=row, column=0)
        self.scan_num_entry = tk.Entry(settings_frame, width=10)
        self.scan_num_entry.insert(0, 10)
        self.scan_num_entry.grid(row=row, column=1, padx=10)
        # Time for the upsweep min -> max
        row += 1
        tk.Label(settings_frame, text="Upsweep time (s)").grid(row=row, column=0)
        self.upsweep_time_entry = tk.Entry(settings_frame, width=10)
        self.upsweep_time_entry.insert(0, 10)
        self.upsweep_time_entry.grid(row=row, column=1)
        # Time for the downsweep max -> min
        row += 1
        tk.Label(settings_frame, text="Downsweep time (s)").grid(row=row, column=0)
        self.downsweep_time_entry = tk.Entry(settings_frame, width=10)
        self.downsweep_time_entry.insert(0, 1)
        self.downsweep_time_entry.grid(row=row, column=1, padx=10)
        # Adding advanced settings
        row += 1
        tk.Label(settings_frame, 
                 text="Advanced settings:", 
                 font='Helvetica 10').grid(row=row, column=0, pady=[10,5], columnspan=3)
        # Number of subpixels to sample (each pixel has this number of samples)
        # Note that excessively large values will slow the scan speed down due to
        # the voltage movement overhead.
        row += 1
        tk.Label(settings_frame, text="# of sub-pixels").grid(row=row, column=0)
        self.subpixel_entry = tk.Entry(settings_frame, width=10)
        self.subpixel_entry.insert(0, 16)
        self.subpixel_entry.grid(row=row, column=1)
        # Button to enable repump at start of scan?
        row += 1
        tk.Label(settings_frame, text="Reump time (s)").grid(row=row, column=0)
        self.repump_entry = tk.Entry(settings_frame, width=10)
        self.repump_entry.insert(0, 0)
        self.repump_entry.grid(row=row, column=1)


        # Define control frame to modify DAQ settings
        control_frame = tk.Frame(main_frame)
        control_frame.pack(side=tk.TOP, padx=0, pady=0)
        # Label
        row += 1
        tk.Label(control_frame, 
                 text="DAQ control", 
                 font='Helvetica 14').grid(row=row, column=0, pady=[20,5], columnspan=2)
        # Setter for the voltage
        row += 1
        self.goto_button = tk.Button(control_frame, text="Set voltage (V)", width=12)
        self.goto_button.grid(row=row, column=0)
        self.laser_setpoint = tk.Entry(control_frame, width=10)
        self.laser_setpoint.insert(0, 1)
        self.laser_setpoint.grid(row=row, column=1, padx=10)
        # Getter for the voltage (based off of the latest set value)
        row += 1
        self.repump_laser_on = tk.IntVar()
        self.repump_laser_toggle_label = tk.Label(control_frame, text='Toggle repump laser')
        self.repump_laser_toggle_label.grid(row=row, column=0, pady=[5,0])
        self.repump_laser_toggle = tk.Checkbutton ( control_frame, var=self.repump_laser_on)
        self.repump_laser_toggle.grid(row=row, column=1, pady=[5,0])




class ScanApplicationView:

    def __init__(self, 
                 window: tk.Toplevel, 
                 application, # ScanApplication
                 settings_dict: dict):
        
        self.application = application
        self.settings_dict = settings_dict

        # Figure properties
        self.norm_min = None
        self.norm_max = None
        # If data viewport should plot the lines (True) or an image (False)
        self.plot_lines = False
        # Names of all input sources to plot
        self.plot_options = application.parent_application.scan_input_channels
        # Name of data channels to plot, defaults to the counter vs scan laser
        self.data_to_plot_x = application.application_controller.scan_laser_id
        self.data_to_plot_y = application.application_controller.counter_id
        # Plot format
        self.plot_format = 'Image'

        # Create the GUI elements
        self.data_viewport = ImageDataViewport(window=window)
        # If there are nondaq elements add them to the list
        if hasattr(self.application.application_controller, 'nondaq_devices'):
            format_options = self.application.application_controller.nondaq_devices
        else:
            format_options = []
        self.control_panel = ImageFigureControlPanel(
            window=window, 
            settings_dict=settings_dict,
            data_options=self.plot_options,
            data_default=self.data_to_plot_y,
            format_options=format_options
        )

        # tkinter right click menu
        self.rclick_menu = tk.Menu(window, tearoff = 0) 

        # Initalize the figure
        self.update_figure()

    def update_figure(self) -> None:
        # Clear the axis
        self.data_viewport.fig.clear()
        # Create a new axis
        self.data_viewport.ax = self.data_viewport.fig.add_subplot(111)

        # Plot either the image or the lines depending on the current configuration
        if self.plot_format == 'Image':
            self._draw_image()
        elif self.plot_format == 'Scans':
            self._draw_lines(average_lines=False)
        elif self.plot_format == 'Average':
            self._draw_lines(average_lines=True)
        # !!!
        # Need to add more options here if you're adding more non-daq devices!
        # !!!
        elif self.plot_format == 'wavemeter':
            self._draw_wavemeter()
        else:
            self._draw_image()

        self.data_viewport.canvas.draw()

    def _draw_image(self):
        '''
        Draws the data as an image
        '''
        # Matplotlib's imshow maps all pixels to the same size. However we want to show both the up
        # and down sweep at the same time which have different scales in voltage. To work around 
        # this, we pick the axis scale from 0 -> 1 on the upscan and 1 -> y_max on the down scan.
        # Proportionality requires
        y_max = 1 + self.application.scan_parameters['n_pixels_down']/self.application.scan_parameters['n_pixels_up'] 

        # Compute the extent of the image
        if self.data_to_plot_y in self.application.data:
            data_to_plot = np.array(self.application.data[self.data_to_plot_y])
        else:
            data_to_plot = np.array([[]]) # If there is no data to plot, make empty array
        n_completed_scans = len(data_to_plot)
        extent = [0.5, 
                  n_completed_scans+0.5,
                  0,
                  y_max]
        # Plot the data
        img = self.data_viewport.ax.imshow(
            data_to_plot.T,
            extent = extent,
            cmap = 'Blues', # Default colormap
            origin = 'lower',
            aspect = 'auto',
            interpolation = 'none'
        )
        # Set the x ticks
        if n_completed_scans < 11:
            # Set ticks on all integer values
            self.data_viewport.ax.set_xticks( np.arange(1,n_completed_scans+1,1) )
        else:
            # Set on every 5 if more than 10 scans long
            self.data_viewport.ax.set_xticks( np.arange(5,n_completed_scans+1,5) )
        # Set the y ticks
        # Place ticks on the upsweep only
        self.data_viewport.ax.set_yticks(
            [0,0.25,0.5,0.75,1.0],
            np.round(
                np.linspace(self.application.scan_parameters['min'], 
                            self.application.scan_parameters['max'],
                            num = 5),
                decimals=3)
        )
        # Add the color bar
        self.data_viewport.cbar = self.data_viewport.fig.colorbar(img, ax=self.data_viewport.ax)
        # Add the labels
        self.data_viewport.ax.set_xlabel('Scan number', fontsize=14)
        self.data_viewport.ax.set_ylabel(self.data_to_plot_x, fontsize=14)
        self.data_viewport.cbar.ax.set_ylabel(self.data_to_plot_y, fontsize=14, rotation=270, labelpad=15)
        self.data_viewport.ax.grid(alpha=0.3, axis='y')
        # Normalize the figure if not already normalized
        if (self.norm_min is not None) and (self.norm_max is not None):
            img.set_norm(plt.Normalize(vmin=self.norm_min, vmax=self.norm_max))

    def _draw_lines(self, average_lines=False):
        '''
            Draws the data as one or more lines
        '''
        # Proportionality requires
        y_max = 1 + self.application.scan_parameters['n_pixels_down']/self.application.scan_parameters['n_pixels_up'] 
        unitless_voltages = np.linspace(
            start=0, 
            stop=y_max, 
            num=self.application.scan_parameters['n_pixels_down']+self.application.scan_parameters['n_pixels_up'])

        # Determine the data to plot
        if self.data_to_plot_y in self.application.data:
            data_to_plot = self.application.data[self.data_to_plot_y]
        else:
            # If there is no data to plot, make empty array
            data_to_plot = [np.empty(self.application.scan_parameters['n_pixels_down']+self.application.scan_parameters['n_pixels_up']),] 
        n_completed_scans = len(data_to_plot)
        if average_lines:
            data_to_plot = [np.average(data_to_plot, axis=0),]
        n_lines_to_plot = len(data_to_plot)
        # Get the color map
        colors = plt.cm.viridis(np.linspace(0,1,n_lines_to_plot))    
        # plot the data
        for line, c in zip(data_to_plot, colors):
            self.data_viewport.ax.plot(
                unitless_voltages,
                line,
                '-',
                c=c
            )    
        # Set the x limits
        self.data_viewport.ax.set_xlim(0,y_max)
        # Place the x ticks on the upsweep only
        self.data_viewport.ax.set_xticks(
            [0,0.25,0.5,0.75,1.0],
            np.round(
                np.linspace(self.application.scan_parameters['min'], 
                            self.application.scan_parameters['max'],
                            num = 5),
                decimals=3)
        )
        # Set the y limits
        self.data_viewport.ax.set_ylim(self.norm_min, self.norm_max)
        # Add the grid and title
        self.data_viewport.ax.grid(alpha=0.3)
        self.data_viewport.ax.set_xlabel(self.data_to_plot_x, fontsize=14)
        self.data_viewport.ax.set_ylabel(self.data_to_plot_y, fontsize=14)
        self.data_viewport.ax.set_title(f'Completed {int(n_completed_scans)} scans')

    def _draw_wavemeter(self):
        if 'upscan_wavemeter_tags' in self.application.data:
            data_x = self.application.data['upscan_wavemeter_tags']
            data_y = self.application.data['upscan_wavemeter_vals']
        else:
            data_x = np.array([0,])
            data_y = np.array([0,])
        
        n_lines_to_plot = len(data_y) 
        # Get the color map
        colors = plt.cm.viridis(np.linspace(0,1,n_lines_to_plot))    
        # plot the data
        for x,y,c in zip(data_x, data_y, colors):
            self.data_viewport.ax.plot(
                np.array(x)-x[0],
                np.array(y),
                '-',
                c=c
            )
        # Add the grid and title
        self.data_viewport.ax.grid(alpha=0.3)
        self.data_viewport.ax.set_xlabel('Wavemeter time tag (10 ms, per scan)', fontsize=14)
        self.data_viewport.ax.set_ylabel('Wavemeter reading (nm or GHz)', fontsize=14)
        self.data_viewport.ax.set_title(f'Completed {int(n_lines_to_plot)} scans')



class ImageDataViewport:

    def __init__(self, window):

        # Parent frame for control panel
        frame = tk.Frame(window)
        frame.pack(side=tk.LEFT, padx=0, pady=0)

        self.fig = plt.figure()
        self.ax = plt.gca()
        self.canvas = FigureCanvasTkAgg(self.fig, master=frame)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        toolbar = NavigationToolbar2Tk(self.canvas, frame)
        toolbar.update()
        self.canvas._tkcanvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas.draw()

# Need to disable the options!!
class ImageFigureControlPanel:

    def __init__(
            self, 
            window: tk.Toplevel, 
            settings_dict: dict, 
            data_options: list, 
            data_default: str,
            format_options: list=[]
    ):

        # Parent frame for control panel
        frame = tk.Frame(window)
        frame.pack(side=tk.TOP, padx=30, pady=20)

        # Frame for saving/modifying data viewport
        command_frame = tk.Frame(frame)
        command_frame.pack(side=tk.TOP, padx=0, pady=0)
        # Add buttons and text
        row = 0
        tk.Label(command_frame, 
                 text='Scan control', 
                 font='Helvetica 14').grid(row=row, column=0, pady=[0,5], columnspan=2)
        # Pause button
        row += 1
        self.stop_button = tk.Button(command_frame, text='Stop scan', width=10)
        self.stop_button.grid(row=row, column=0, columnspan=1, padx=5, pady=[0,5])
        # Continue button
        self.save_button = tk.Button(command_frame, text='Save scan', width=10)
        self.save_button.grid(row=row, column=1, columnspan=1, padx=5, pady=[0,5])

        # ===============================================================================
        # Add more buttons or controls here
        # ===============================================================================

        # Define settings frame to set all scan settings
        settings_frame = tk.Frame(frame)
        settings_frame.pack(side=tk.TOP, padx=0, pady=[10,0])
        # Min voltage
        row += 1
        tk.Label(settings_frame, text="Min voltage (V)").grid(row=row, column=0)
        self.voltage_start_entry = tk.Entry(settings_frame, width=10)
        self.voltage_start_entry.insert(0, settings_dict['min'])
        self.voltage_start_entry.config(state='readonly')
        self.voltage_start_entry.grid(row=row, column=1)
        # Max voltage
        row += 1
        tk.Label(settings_frame, text="Max voltage (V)").grid(row=row, column=0)
        self.voltage_end_entry = tk.Entry(settings_frame, width=10)
        self.voltage_end_entry.insert(0, settings_dict['max'])
        self.voltage_end_entry.config(state='readonly')
        self.voltage_end_entry.grid(row=row, column=1)
        # Number of pixels on upsweep
        row += 1
        tk.Label(settings_frame, text="# of pixels up").grid(row=row, column=0)
        self.num_pixels_up_entry = tk.Entry(settings_frame, width=10)
        self.num_pixels_up_entry.insert(0, settings_dict['n_pixels_up'])
        self.num_pixels_up_entry.config(state='readonly')
        self.num_pixels_up_entry.grid(row=row, column=1)
        # Number of pixels on downsweep
        row += 1
        tk.Label(settings_frame, text="# of pixels down").grid(row=row, column=0)
        self.num_pixels_down_entry = tk.Entry(settings_frame, width=10)
        self.num_pixels_down_entry.insert(0, settings_dict['n_pixels_down'])
        self.num_pixels_down_entry.config(state='readonly')
        self.num_pixels_down_entry.grid(row=row, column=1)
        # Number of scans
        row += 1
        tk.Label(settings_frame, text="# of scans").grid(row=row, column=0)
        self.scan_num_entry = tk.Entry(settings_frame, width=10)
        self.scan_num_entry.insert(0, settings_dict['n_scans'])
        self.scan_num_entry.config(state='readonly')
        self.scan_num_entry.grid(row=row, column=1, padx=10)
        # Time for the upsweep min -> max
        row += 1
        tk.Label(settings_frame, text="Upsweep time (s)").grid(row=row, column=0)
        self.upsweep_time_entry = tk.Entry(settings_frame, width=10)
        self.upsweep_time_entry.insert(0, settings_dict['time_up'])
        self.upsweep_time_entry.config(state='readonly')
        self.upsweep_time_entry.grid(row=row, column=1)
        # Time for the downsweep max -> min
        row += 1
        tk.Label(settings_frame, text="Downsweep time (s)").grid(row=row, column=0)
        self.downsweep_time_entry = tk.Entry(settings_frame, width=10)
        self.downsweep_time_entry.insert(0, settings_dict['time_down'])
        self.downsweep_time_entry.config(state='readonly')
        self.downsweep_time_entry.grid(row=row, column=1, padx=10)
        # Subpixel number
        row += 1
        tk.Label(settings_frame, text="# of sub-pixels").grid(row=row, column=0)
        self.subpixel_entry = tk.Entry(settings_frame, width=10)
        self.subpixel_entry.insert(0, settings_dict['n_subpixels'])
        self.subpixel_entry.config(state='readonly')
        self.subpixel_entry.grid(row=row, column=1)
        # Repump time
        row += 1
        tk.Label(settings_frame, text="Reump time (s)").grid(row=row, column=0)
        self.repump_entry = tk.Entry(settings_frame, width=10)
        self.repump_entry.insert(0, settings_dict['time_repump'])
        self.repump_entry.config(state='readonly')
        self.repump_entry.grid(row=row, column=1)

        # ===============================================================================
        # Add additional scan settings if implemented later
        # ===============================================================================

        # Scan settings view
        image_settings_frame = tk.Frame(frame)
        image_settings_frame.pack(side=tk.TOP, padx=0, pady=0)
        # Single axis scan section
        row = 0
        tk.Label(image_settings_frame, 
                 text='Image settings', 
                 font='Helvetica 14').grid(row=row, column=0, pady=[10,5], columnspan=2)
        # Minimum
        row += 1
        tk.Label(image_settings_frame, text='Minimum (cts/s)').grid(row=row, column=0, padx=5, pady=2)
        self.image_minimum = tk.Entry(image_settings_frame, width=10)
        self.image_minimum.insert(0, 0)
        self.image_minimum.grid(row=row, column=1, padx=5, pady=2)
        # Maximum
        row += 1
        tk.Label(image_settings_frame, text='Maximum (cts/s)').grid(row=row, column=0, padx=5, pady=2)
        self.image_maximum = tk.Entry(image_settings_frame, width=10)
        self.image_maximum.insert(0, 10000)
        self.image_maximum.grid(row=row, column=1, padx=5, pady=2)

        # Scan settings view
        image_settings_buttons_frame = tk.Frame(frame)
        image_settings_buttons_frame.pack(side=tk.TOP, padx=0, pady=0)
        # Single axis scan section
        row = 1
        self.norm_button = tk.Button(image_settings_buttons_frame, text='Normalize', width=10)
        self.norm_button.grid(row=row, column=0, columnspan=1, padx=5, pady=[5,1])
        # Autonormalization button
        self.autonorm_button = tk.Button(image_settings_buttons_frame, text='Auto-norm', width=10)
        self.autonorm_button.grid(row=row, column=1, columnspan=1, padx=5, pady=[5,1])
        # Data to plot selection
        row += 1
        self.selected_option = tk.StringVar(image_settings_buttons_frame)
        self.selected_option.set(data_default)  # Set the default option
        self.selection_dropdown = tk.OptionMenu(image_settings_buttons_frame, self.selected_option, *data_options)
        self.selection_dropdown.grid(row=row, column=0, columnspan=2, padx=5, pady=[5,1])
        # Data format selection
        row += 1
        self.format_option = tk.StringVar(image_settings_buttons_frame)
        self.format_option.set('Image')  # Set the default option
        self.format_dropdown = tk.OptionMenu(image_settings_buttons_frame, self.format_option, *(['Image', 'Scans', 'Average']+format_options))
        self.format_dropdown.grid(row=row, column=0, columnspan=2, padx=5, pady=5)
    


        # ===============================================================================
        # Add more buttons or controls here
        # ===============================================================================
