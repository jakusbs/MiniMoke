# Introduction

This comprehensive software documentation is designed to guide you through the usage of the MiniMOKE setup in conjunction with our software. The software supports functionalities such as magnetic field ramping, X and Y position sweeps, and facilitates measurements in DC and AC modes using a "home-made" Lockin demodulation algorithm.

# User Interface Overview

The software's user interface is designed for simplicity and ease of use. It offers straightforward access to all the necessary tools and features required for running measurements with the MiniMOKE setup. Below are the main components of the user interface:

- **Experiment Tabs**: Located on the left, these tabs allow users to define all necessary parameters for each type of experiment.
- **Experiment Launcher**: Positioned at the bottom-left, this section enables users to set the output folder and the sample name, and to queue one or more experiments.
- **Main Tabs**: These tabs offer access to the core features of the software:
    - *User Manual Tab*: Access the user manual.
    - *Motor Control Tab*: Manually control the 3D stage on an axis-by-axis basis or directly go to a specific position. Use the 'Home' buttons to reset the current position to zero.
    - *Live Measurements Tab*: Monitor live values from the Hall probe, the intensity diode, and the balanced diodes, provided no experiment is running.
    - *Results Graph Tab*: This provides live visualization of the measurements from each experiment, with the ability to customize the X and Y data for the plot.
    - *Experiment Log*: Track current and past actions via the log, helpful for troubleshooting failed experiments.
- **Experiment Queue**: Located at the bottom, this enables users to choose which experiment to plot and to check the status of each experiment.
- **Status Bar**: Located at the very bottom, this bar displays the latest log entry.

<img src="assets/interface_sc_01.png" alt="Interface Screenshot 01" width="1000">

# Performing a Measurement

To conduct a measurement using this software, adhere to the following steps:

- Use the "Live Measurements" tab under the "Main Tabs" to view the live values of the balanced diodes. Calibrate them and zero the Hall probe, if necessary.
- From the "Experiment Tabs", choose the type of experiment you wish to perform (i.e., "B-Sweep", "X-Sweep", "Y-Sweep", "XY-Sweep") and configure all the parameters.
- In the "Experiment Launcher" section:
    - Enter your sample's name and select the number of times you wish to repeat this particular experiment.
    - Click the folder icon to designate the output folder where the data will be stored.
    - Click "Queue" to add the experiment to the queue. If the "Resume" button appears and the experiment doesn't start immediately, click it.
- (Optional) To halt the experiment, click "Abort".
- Preview the data in the "Results Graph" tab under the "Main Tabs". Here, you can select the datasets for the X and Y data for the graph.
- Use the "Experiment Queue" section to check when the experiment has completed, visible in the "Status" column.

# Tips and Tricks

- When you queue an experiment, all the parameter values are stored, allowing you to retrieve them even after the program has been closed.
- In the "Results Graph" tab, a right-click on the plot allows you to:
    - Apply mathematical functions such as computing the derivative, plotting the Fourier transform, or taking the average.
    - Recenter the plot using "View All".
    - Export the current graph directly as a .csv, .png, or .svg file.
- In the "Results Graph" tab, hold the right click and slide vertically or horizontally to zoom in or out.
- In the "Experiment Queue" section, clicking "Open" allows you to open and plot an experiment saved by this software.
- In the "Experiment Queue" section, a right-click on an experiment gives you the ability to:
    - Reuse its parameters
    - Change its color
    - Open the saved data
    - Remove it from the list
    - Delete it (use this option with caution)