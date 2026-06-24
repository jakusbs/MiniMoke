"""
Description:
    Defines a HallSensor class for interacting with a Hall probe.
    This class uses the MagnetPhysik dll. Please be careful, this is a .NET DLL.
    The DLL you can find on MagnetPhysik's website is in 32bit which won't work
    with 64bit Python. Please use the DLL provides in the libs folder.
"""

from time import sleep
import os

DLL_working = False

try:
    import clr
    # Use a raw string for the path to avoid escape character issues
    dll_path = r'C:/Users/intermag/Documents/minimoke/libs/MagnetPhysik.Usb.dll'
    
    if os.path.exists(dll_path):
        clr.AddReference(dll_path)
        import MagnetPhysik as MP
        DLL_working = True
    else:
        print(f"DLL not found at: {dll_path}")
except Exception as e:
    print(f"DLL Load Error: {e}")
    print("Ensure you are using 64-bit Python.")

class HallSensor:
    def __init__(self) -> None:
        """
        Initialize the HallSensor object.
        """
        self.enabled                = False
        self.reserved               = False

        if DLL_working:
            try: 
                self.hall_sensor        = MP.HallProbe()
                # Define the speed of the sensor, see the corresponding sampling rate in the function "get_sampling_rate"
                self.hall_sensor.Speed  = 1
                # Set a default aquisition time
                self.enabled            = True
            except: pass
        
        self.set_aquisition_time(0.5)

    def set_aquisition_time(self, time) -> None:
        """
        Set the acquisition time of the Hall sensor.
        The aquisition time is in fact set by the number of points used by the filter

        Args:
            time (float): The desired acquisition time in seconds.
        """

        if not self.enabled:
            self.aquisition_time = time
            return

        # Parameter 0: filter off, 2...255: number of filter points
        self.hall_sensor.Filter = max(min(255, round(time * self.get_sampling_rate())), 0)
        self.aquisition_time    = self.hall_sensor.Filter / self.get_sampling_rate()

    def read_mT(self) -> float:
        """
        Read the magnetic field value measured by the sensor in millitesla (mT) and return it.

        Returns:
            float or None: The measured magnetic field value in mT, or None if an error occurred.
        """
        sleep(self.aquisition_time)

        if not self.enabled: return

        try:
            return self.hall_sensor.get_Tesla() * 1000.
        except:
            return None

    def zeroing(self) -> None:
        """
        Perform zeroing of the Hall probe. This should be done at 0 magnetic field.
        """
        if not self.enabled: return

        # Ask the sensor to start zeroing
        self.hall_sensor.Zero = True

        # Wait for the zeroing to be done
        while self.hall_sensor.Zero: pass

    def get_sampling_rate(self) -> float:
        """
        Specific to the sensor used for this application!
        Convert the speed byte to the sampling rate used by the sensor.

        Returns:
            float: The sampling rate used by the sensor
        """

        if not self.enabled: return 0

        index_to_frequency_dict = {
            15: 4.17,
            14: 6.25,
            13: 8.33,
            12: 10,
            11: 12.5,
            10: 16.7,
            9: 16.7,
            8: 19.6,
            7: 33.2,
            6: 39,
            5: 50,
            4: 62,
            3: 123,
            2: 242,
            1: 470
        }
        
        return index_to_frequency_dict.get(self.hall_sensor.Speed, 1.)