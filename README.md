# MiniMOKE

This repository hosts the user interface software for the MiniMOKE experimental setup.

## Prerequisites

To run this project, you'll need a Conda or Miniconda environment with Python 3.6 (64-bit) or newer. Create an environment by executing the following command: 

```bash
conda create --name MOKE python=3.11 
```

To view the list of available environments, run:

```bash
conda env list
```

Subsequently, install the necessary modules:

```bash
conda install -c conda-forge pylablib
conda install -c conda-forge pythonnet
conda install pyinstaller
pip install pymeasure
pip install nidaqmx
pip install markdown
pip install qdarkstyle
pip install pyft232
pip install pytrinamic
```

## Usage

If you're unsure of the correct environment to use, please run the program using the batch scripts located in the `scripts` folder which will automatically run the correct file using the `NOKE` env.

## Code Structure

Here's a breakdown of the project structure:

- `minimoke/libs`: Houses the project's library files, such as `MagnetPhysik.Usb.dll`.

- `minimoke/.gitignore`: Git uses this file to identify which files and directories to exclude from the project.

- `minimoke/configs`: Stores the configuration files (INI files) for stages, procedures, and DAC.

- `minimoke/scripts`: Contains the build and debug scripts, as well as the PyInstaller JSON configuration file.

- `minimoke/doc`: Contains the user manual for the software.

- `minimoke/assets`: Contains the image files and icons utilized by the software.

- `minimoke/__main__.py`: Serves as the primary entry point for the software.

- `minimoke/src`: Holds the source code files for the software, divided into the following directories:

    - `minimoke/src/procedures`: Contains source code for different experimental procedures, including Y-Sweep, B-Sweep, X-Sweep, and XY-Sweep.

    - `minimoke/src/ui`: Contains source code for the User Interface (UI), including the main UI, User Manual Tab UI, Live Tab UI, and Motors Tab UI.

    - `minimoke/src/classes`: Contains source code for various classes used in the software, including StatusBar class, DAC class, Stage class, ConfigHandler class, and HallSensor class.