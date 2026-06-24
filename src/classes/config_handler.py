"""
Description:
    This file provides a simple-to-use class, Config, which wraps the configparser library. 
    The Config class is designed to facilitate the handling of configuration files, making it easy to save and retrieve values.
    It serves as a convenient solution for preserving variables when closing the software.

    Create instances of the Config class to handle different
    configuration files as global variables
"""

import configparser

class Config:
    def __init__(self, file) -> None:
        """
        Initialize the Config object.
        
        Args:
            file (str): The path to the configuration file.
        """
        self.file = file
        self.config = configparser.ConfigParser()
        self.read()

    def read(self) -> None:
        """
        Read the configuration file. The config object now contains the variables and values from the file."""
        self.config.read(self.file)

    def get_section(self, section_name) -> dict:
        """
        Retrieve a specific section from the configuration as a dictionary.
        
        Args:
            section_name (str): The name of the section to retrieve.
        
        Returns:
            dict: A dictionary containing the key-value pairs for each variable of the section,
                  or an empty dictionary if the section does not exist.
        """
        # Check if the section exists in the config file and return it
        if section_name in self.config:
            return self.config[section_name]
        # Otherwise, return an empty dictionnary
        return dict()

    def save_str_dict(self, section_name, str_variables_dict) -> None:
        """
        Save a dictionary of string variables into a section of the configuration file.
        
        Args:
            section_name (str): The name of the section to save the variables into.
            str_variables_dict (dict): A dictionary of string variables to save.
        """
        # Update the variables in the section with the given dictionnary
        self.config[section_name] = str_variables_dict

        # Save the config file with the updated variables
        with open(self.file, "w") as config_file:
            self.config.write(config_file)

    def save_parameters_dict(self, section_name, parameters_variables_dict) -> None:
        """
        Save a dictionary of parameter variables into a section of the configuration file.
        
        Args:
            section_name (str): The name of the section to save the variables into.
            parameters_variables_dict (dict): A dictionary of parameter variables to save.
        """
        variables_dict = dict()

        for name, parameter in parameters_variables_dict.items():
            variables_dict[name] = str(parameter.value)
    
        self.config[section_name] = variables_dict
        with open(self.file, "w") as config_file:
            self.config.write(config_file)

# Create an instance of Config to handle the inputs variables of the procedures
proc_config     = Config('configs/procedures_config.ini')

# Config for the longitudinal motor stage
longitudinal_stage_config = Config('configs/longitudinal_stage_config.ini')

# Create another instance of Config to handle the DAC configuration with the I/O ports
dac_config          = Config('configs/dac_config.ini')

# Config for the polar motor stage (separate serial numbers and offsets)
polar_stage_config  = Config('configs/polar_stage_config.ini')