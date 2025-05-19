import importlib
import importlib.resources
import logging
import numpy as np
import datetime
import h5py

from threading import Thread
import tkinter as tk
import yaml

import qdlutils
from qdlutils.applications.qdlple2.application_controller import PLEControllerBase
from qdlutils.applications.qdlple2.application_gui import (
    LauncherApplicationView,
    ScanApplicationView
)
import qdlutils.applications.qdlscope.main as qdlscope

from typing import Union, Any

logger = logging.getLogger(__name__)
logging.basicConfig()

CONFIG_PATH = 'qdlutils.applications.qdlple2.config_files'
DEFAULT_CONFIG_FILE = 'qdlple2_base.yaml'

# Default color map
DEFAULT_COLOR_MAP = 'gray'


class LauncherApplication:

    # Type hints
    application_controller: PLEControllerBase

    def __init__(
            self, 
            default_config_filename: str, 
            is_root_process: bool
    ) -> None:
        '''
        Initialization for the LauncherApplication class for the new version of `qdlple`. It loads 
        the application controller then creates a GUI and binds the buttons. Callback methods for
        GUI interactions are contained in this class.
        
        Parameters
        ----------
        config_file: str
            Filename of the default config YAML file. It must be located in the
            `qdlple/config_files` directory.
        is_root_process: bool
            `True` if the launcher application is running the toplevel `tkinter` process.
        '''
        # Boolean if the function is the root or not, determines if the application is
        # intialized via tk.Tk or tk.Toplevel
        self.is_root_process = is_root_process
        # Application controller
        self.application_controller = None
        # Number of scan windows launched
        self.number_scans = 0
        # Reference to child scan windows
        self.scan_applications = []
        # Last save directory
        self.last_save_directory = None
        # Store the GUI input values
        self.gui_input = None

        # Data to load from YAML
        # Instructions for processing data
        self.processing_instructions = {}
        # Input source names
        self.input_source_names = None
        # Output source names
        self.ouptut_source_names = None

        # Load the YAML file
        self.configure_from_yaml(yaml_filename=default_config_filename)

        # Initialize the root tkinter widget (window housing GUI)
        if self.is_root_process:
            self.root = tk.Tk()
        else:
            self.root = tk.Toplevel()
        # Create the main application GUI
        self.view = LauncherApplicationView(main_window=self.root)

        # Bind the GUI buttons to callback functions
        self.view.control_panel.start_button.bind("<Button>", self.start_scan)
        self.view.control_panel.goto_button.bind("<Button>", self.set_laser)
        self.view.control_panel.repump_laser_toggle.config(command=self.toggle_repump_laser)

    def run(self) -> None:
        '''
        Launches the application and GUI
        '''
        # Set the title of the app window
        self.root.title('qdlple')
        # Display the window (not in task bar)
        self.root.deiconify()
        # Launch the main tk loop if the root process
        if self.is_root_process:
            self.root.mainloop()

    def configure_from_yaml(
            self,
            yaml_filename: str
    ) -> None:
        '''
        Opens the YAML file, extracts configuration data and loads the appropriate classes.
        '''

        # Get the full path for the YAML file
        yaml_path = importlib.resources.files(CONFIG_PATH).joinpath(yaml_filename)
        # Safe load the file into the `config` dict
        with open(str(yaml_path), 'r') as file:
            # Log selection
            logger.info(f"Loading settings from: {yaml_path}")
            # Get the YAML config as a nested dict
            config = yaml.safe_load(file)

        # Get top level
        app_name = list(config.keys())[0]

        # Get the config of the application controller
        controller_config = config[app_name]['ApplicationController']
        # Get the config of the hardware groups
        hardware_config = config[app_name]['HardwareGroups']
        # Get the config of the channels
        channel_config = config[app_name]['Channels']

        # First get the application controller class path/name and generate a constructor
        ctrl_import_path = controller_config['import_path']
        ctrl_class_name = controller_config['class_name']
        module = importlib.import_module(ctrl_import_path)
        logger.debug(f'Importing {ctrl_import_path}')
        constructor = getattr(module, ctrl_class_name)
        # Load the controller input parameters
        ctrl_params = controller_config['configure']

        # Load the scan inputs
        scan_inputs, scan_inputs_instr = self._load_io_groups(
            groups_to_load=ctrl_params['scan_inputs'],
            hardware_config=hardware_config,
            channel_config=channel_config
        )
        # Load the scan outputs
        scan_outputs, scan_outputs_instr = self._load_io_groups(
            groups_to_load=ctrl_params['scan_outputs'],
            hardware_config=hardware_config,
            channel_config=channel_config
        )
        # Load the repump inputs
        repump_inputs, repump_inputs_instr = self._load_io_groups(
            groups_to_load=ctrl_params['repump_inputs'],
            hardware_config=hardware_config,
            channel_config=channel_config
        )
        # Load the scan outputs
        repump_outputs, repump_outputs_instr = self._load_io_groups(
            groups_to_load=ctrl_params['repump_outputs'],
            hardware_config=hardware_config,
            channel_config=channel_config
        )

        # Add/update the controller parameters
        ctrl_params['scan_inputs'] = scan_inputs
        ctrl_params['scan_outputs'] = scan_outputs
        ctrl_params['repump_inputs'] = repump_inputs
        ctrl_params['repump_outputs'] = repump_outputs
        ctrl_params['process_instructions'] = {
            **scan_inputs_instr, **scan_outputs_instr, **repump_inputs_instr, **repump_outputs_instr
        }

        # Create the controller
        self.application_controller = constructor(**ctrl_params)
        
    def _load_io_groups(
            self,
            groups_to_load: dict[str,Any],
            hardware_config: dict[str,Any],
            channel_config: dict[str,Any]
    ):
        '''
        Creates dictionary of input/output groups specified by the controller YAML configuration

        Parameters
        ----------
        name: str
            Name of the inputs/outputs to load

        Returns
        -------
        groups: dict[str,dict[str,Any]]
            A dictionary of the input/output groups associated to the controller parameter specified
            by the `name`.
        process_instructions: dict[str,str]
            Process instructions for the channels in the loaded groups
        '''
        # Dictionaries to hold the io groups and process instructions 
        groups = {}
        process_instructions = {}
        # Iterate through the groups, construct them and then save them in the `groups` dict.
        for group in groups_to_load:
            # Get the group configuration dictionary
            group_dict = hardware_config[group]
            # Get the path and class name, make the constructor
            group_import_path = group_dict['import_path']
            group_class_name = group_dict['class_name']
            module = importlib.import_module(group_import_path)
            logger.debug(f'Importing {group_import_path}')
            group_constructor = getattr(module, group_class_name)
            # Get the channels. This is a dicitonary where each key-value pair describes a channel 
            # in the group and it's corresponding configuration information.
            channels = {}
            for channel in group_dict['channels']:
                # Get the channel config dict
                channels[channel] = channel_config[channel]
                if channel_config[channel]['process_instructions'] is not None:
                    process_instructions[channel] = channel_config[channel]['process_instructions']
            # Add groups to output dictionary
            groups[group] = group_constructor(channels_config = channels)

        return groups, process_instructions

    def set_laser(
            self,
            tkinter_event=None
    ) -> None:
        '''
        Sets the frequency of the laser to the value determined by the set point provided in the GUI
        input window.

        Parameters
        ----------
        tkinter_event: tk.Event
            The button press event, not used.
        '''
        try:
            # Read the current inputs in the GUI
            self._read_gui()
            # Set the scan laser value
            self.application_controller.set_output(
                output_id=self.application_controller.scan_laser_id, 
                setpoint=self.gui_input['laser_setpoint']
            )
        except Exception as e:
            logger.error(f'Error with setting laser: {e}')

    def toggle_repump_laser(
            self, 
            set_value: bool = None
    ) -> None:
        '''
        Callback to toggle the repump laser. If called outside of a callback function, the parameter
        `set_value` determines the toggled state, independent of the GUI.
        '''

        try: 
            # If the GUI toggle is on and no direct command `cmd` given
            # OR if the direct command is True then turn on the laser
            if (self.view.control_panel.repump_laser_on.get() == 1) or (set_value is True):
                logger.info('Turning repump laser on.')
                self.application_controller.set_output(
                    output_id=self.application_controller.repump_laser_id, 
                    setpoint=self.application_controller.repump_laser_setpoints['on']
                )
            # Else if the GUI toggle is off and no direct command is given
            # OR if the direct command is False then turn off the laser
            elif (self.view.control_panel.repump_laser_on.get() == 0) or (set_value is False):
                logger.info('Turning repump laser off.')
                self.application_controller.set_output(
                    output_id=self.application_controller.repump_laser_id, 
                    setpoint=self.application_controller.repump_laser_setpoints['off']
                )
        except AttributeError as e:
            logger.error(f'Repump laser could not be toggled: {e}')

    def _read_gui(
            self
    ) -> None:
        '''
        Reads the current input from the GUI and saves data to `self.gui_input`. Returns the scan
        configuration dictionary
        '''

        # Read the values from the GUI
        min = float(self.view.control_panel.voltage_start_entry.get())
        max = float(self.view.control_panel.voltage_end_entry.get())
        n_pixels_up = int(self.view.control_panel.num_pixels_up_entry.get())
        n_pixels_down = int(self.view.control_panel.num_pixels_down_entry.get())
        n_subpixels = int(self.view.control_panel.subpixel_entry.get())
        time_up = float(self.view.control_panel.upsweep_time_entry.get())
        time_down = float(self.view.control_panel.downsweep_time_entry.get())
        time_repump = float(self.view.control_panel.repump_entry.get())
        n_scans = int(self.view.control_panel.scan_num_entry.get())
        set_voltage = float(self.view.control_panel.voltage_entry.get())

        # Get the scan configuration parameters
        scan_config_params = {
            'min' : min,
            'max' : max,
            'n_pixels_up' : n_pixels_up,
            'n_pixels_down' :  n_pixels_down,
            'n_subpixels' : n_subpixels,
            'time_up' : time_up,
            'time_down' : time_down,
            'time_repump' : time_repump,
        }

        # Set the GUI input
        self.gui_input = {
            **scan_config_params,
            'n_scans' : n_scans,
            'set_voltage' : set_voltage
        }

        return scan_config_params

    def start_scan(
            self,
            tkinter_event = None,
    ) -> None:
        '''
        Callback to start scan button. Launches a new ScanApplication which manages the scan.
        '''
        if self.application_controller.busy:
            logger.error(f'Application controller is current busy.')
            return None
        logger.info('Starting PLE scans.')
        # Update the parameters
        try:
            # Read the gui and get the scan parameters
            scan_parameters = self._read_gui()
        except Exception as e:
            logger.error(f'Scan parameters are invalid: {e}')
            return None
        # Increase the nunmber of scans launched
        self.number_scans += 1
        # Launch a image scan application
        self.current_scan = ScanApplication(
            parent_application = self,
            application_controller = self.application_controller,
            scan_parameters=scan_parameters,
            n_scans = self.gui_input['n_scans'],
            id = str(self.number_scans).zfill(3)
        )
    


class ScanApplication:

    def __init__(
            self,
            parent_application: LauncherApplication,
            application_controller: PLEControllerBase,
            scan_parameters: dict,
            n_scans: int,
            id: str
    ):
        self.parent_application = parent_application
        self.application_controller = application_controller
        self.scan_parameters = scan_parameters
        self.n_scans = n_scans
        self.id = id
        self.timestamp = datetime.datetime.now()

        # Create a dictionary to store the data
        self.data = {}

        # Configure the sequencer, an error will be thrown 
        self.application_controller.configure_sequence(
            **scan_parameters
        )

        # Then initialize the GUI
        self.root = tk.Toplevel()
        self.root.title(f'Scan {id} ({self.timestamp.strftime("%Y-%m-%d %H:%M:%S")})')
        self.view = ScanApplicationView(
                window=self.root, 
                application=self,
                settings_dict={**scan_parameters, 'n_scans': n_scans}
        )

        # Bind the buttons
        self.view.control_panel.stop_button.bind("<Button>", self.stop_scan)
        self.view.control_panel.save_button.bind("<Button>", self.save_scan)
        #self.view.control_panel.norm_button.bind("<Button>", self.set_normalize)
        #self.view.control_panel.autonorm_button.bind("<Button>", self.auto_normalize)

        # Launch the thread
        self.scan_thread = Thread(target=self.scan_thread_function)
        self.scan_thread.start()

    def scan_thread_function(self) -> None:

        try:
            for scan_data in self.application_controller.run_n_sequences(
                    n=self.n_scans,
                    process_method=self.application_controller.process_data,
                    process_kwargs=self.application_controller.process_instructions,
            ):
                # Each yield gets new `scan_data` which is a dictionary with all the entires defined
                # in `PLEController.process_data()`. We will generally not know what these are ahead
                # of time and so we must programatically define them.
                # The first time we need to just save the data directly, here using a dictionary
                # comprehension to place the values in lists:
                if self.data is None:
                    self.data = {k: [v,] for k,v in scan_data.items()}
                # On the later scans we can simply append
                else:
                    for result in scan_data:
                        self.data[result].append(scan_data[result])
                    
                # Update the figure
                self.view.update_figure()

                logger.debug('Row complete.')

            logger.info('Scan complete.')

        except Exception as e:
            logger.error(f'Error in scan thread: {e}')

    def stop_scan(
            self,
            tkinter_event: tk.Event = None
    ) -> None: 
        pass

    def save_scan(
            self,
            tkinter_event: tk.Event = None
    ) -> None:
        pass





def main(is_root_process=True):
    tkapp = LauncherApplication(
        default_config_filename=DEFAULT_CONFIG_FILE,
        is_root_process=is_root_process)
    tkapp.run()

if __name__ == '__main__':
    main()
