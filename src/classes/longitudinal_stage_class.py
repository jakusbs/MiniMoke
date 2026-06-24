"""
Description:
    This file  defines a Stage class for controlling a 3D stage device.
    It uses the Thorlabs library and connects to the KinesisMotors.
    This class allow homing of the motors, moving them and reading oout their position

"""

from pylablib.devices import Thorlabs
from src.classes import longitudinal_stage_config as stage_config

class LongitudinalStage:
    enabled = False

    def __init__(self) -> None:
        """
        Initialize the Stage object.
        Get the serial number corresponding to the motors for each axis
        from the configuration file "stage_config".
        If one motor is not found, the stage is disactivated.
        """
        serial_numbers = stage_config.get_section("Serials")

        try:
            self.motor_x = Thorlabs.KinesisMotor(serial_numbers.get("x", "0"))
            self.motor_y = Thorlabs.KinesisMotor(serial_numbers.get("y", "0"))
            self.motor_z = Thorlabs.KinesisMotor(serial_numbers.get("z", "0"))
            self.enabled = True
        except Exception as err:
            print(f"Unexpected {err=} during stage init, {type(err)=}")
            self.enabled = False

        constants = stage_config.get_section("Constants")
        self.mm2steps = float(constants.get("mm2steps", "1"))

        self.load_offsets()

    def load_offsets(self) -> None:
        """
        Load the stage offsets from the configuration file.
        The offset are used to manually home the motors.
        """
        offsets = stage_config.get_section("Offsets")
        self.offset_x = float(offsets.get("offset_x", "0"))
        self.offset_y = float(offsets.get("offset_y", "0"))
        self.offset_z = float(offsets.get("offset_z", "0"))

    def save_config(self) -> None:
        """
        Save the stage offsets, to the configuration file.
        """
        stage_config.save_str_dict("Offsets", {
            "offset_x": str(self.offset_x),
            "offset_y": str(self.offset_y),
            "offset_z": str(self.offset_z)
        })

    def home_axis(self, axis=None) -> None:
        """
        Home the specified axis or all axes of the stage if the axis is not specified.

        Args:
            axis (str or None): The axis to home ('x', 'y', 'z') or None to home all axes.
        """
        if self.enabled:
            if axis is None:
                self.offset_x = self.motor_x.get_position(scale=False)
                self.offset_y = self.motor_y.get_position(scale=False)
                self.offset_z = self.motor_z.get_position(scale=False)
            elif axis == 'x':
                self.offset_x = self.motor_x.get_position(scale=False)
            elif axis == 'y':
                self.offset_y = self.motor_y.get_position(scale=False)
            elif axis == 'z':
                self.offset_z = self.motor_z.get_position(scale=False)
            self.save_config()

    def wait_stable(self) -> None:
        """
        Wait for the stage motors to reach a stable position.
        """
        if self.enabled:
            self.motor_x.wait_move
            self.motor_y.wait_move
            self.motor_z.wait_move

    #################################################################
    # MOVE MOTORS BY A NUMBER OF STEPS
    #################################################################

    def move_x(self, mm) -> None:
        """
        Move the X-axis motor by a specified distance in millimeters.

        Args:
            mm (float): The distance to move in millimeters.
        """
        if self.enabled and not self.motor_x.is_moving():
            self.motor_x.move_by(mm * self.mm2steps, scale=False)
            self.motor_x.wait_move()

    def move_y(self, mm) -> None:
        """
        Move the Y-axis motor by a specified distance in millimeters.

        Args:
            mm (float): The distance to move in millimeters.
        """
        if self.enabled and not self.motor_y.is_moving():
            self.motor_y.move_by(-mm * self.mm2steps, scale=False)
            self.motor_y.wait_move()

    def move_z(self, mm) -> None:
        """
        Move the Z-axis motor by a specified distance in millimeters.

        Args:
            mm (float): The distance to move in millimeters.
        """
        if self.enabled and not self.motor_z.is_moving():
            self.motor_z.move_by(mm * self.mm2steps, scale=False)
            self.motor_z.wait_move()

    #################################################################
    # MOVE MOTORS TO A GIVEN POSITION
    #################################################################

    def move_x_to(self, position) -> None:
        """
        Move the X-axis motor to the specified position in millimeters.

        Args:
            position (float): The position to move to in millimeters.
        """
        if self.enabled:
            self.motor_x.move_to(position * self.mm2steps + self.offset_x, scale=False)
            self.motor_x.wait_move()

    def move_y_to(self, position) -> None:
        """
        Move the Y-axis motor to the specified position in millimeters.

        Args:
            position (float): The position to move to in millimeters.
        """
        if self.enabled:
            self.motor_y.move_to(position * self.mm2steps + self.offset_y, scale=False)
            self.motor_y.wait_move()

    def move_z_to(self, position) -> None:
        """
        Move the Z-axis motor to the specified position in millimeters.

        Args:
            position (float): The position to move to in millimeters.
        """
        if self.enabled:
            self.motor_z.move_to(position * self.mm2steps + self.offset_z, scale=False)
            self.motor_z.wait_move()

    #################################################################
    # GET THE POSITION
    #################################################################

    def get_x_pos(self) -> float:
        """
        Get the X-axis position in millimeters.

        Returns:
            float: The X-axis position in millimeters.
        """
        if not self.enabled: return float('nan')
        return (self.motor_x.get_position(scale=False) - self.offset_x) / self.mm2steps

    def get_y_pos(self) -> float:
        """
        Get the Y-axis position in millimeters.

        Returns:
            float: The Y-axis position in millimeters.
        """
        if not self.enabled: return float('nan')
        return (self.motor_y.get_position(scale=False) - self.offset_y) / self.mm2steps

    def get_z_pos(self) -> float:
        """
        Get the Z-axis position in millimeters.

        Returns:
            float: The Z-axis position in millimeters.
        """
        if not self.enabled: return float('nan')
        return (self.motor_z.get_position(scale=False) - self.offset_z) / self.mm2steps
    
    #################################################################
    # GET THE POSITION AS A FORMATTED STRING
    #################################################################

    def get_x_pos_str(self) -> str:
        """
        Get the X-axis position as a formatted string.

        Returns:
            str: The X-axis position as a formatted string.
        """
        if not self.enabled: return "?"
        return f"{(self.motor_x.get_position(scale=False) - self.offset_x) / self.mm2steps:.{3}f}mm"

    def get_y_pos_str(self) -> str:
        """
        Get the Y-axis position as a formatted string.

        Returns:
            str: The Y-axis position as a formatted string.
        """
        if not self.enabled: return "?"
        return f"{(self.motor_y.get_position(scale=False) - self.offset_y) / self.mm2steps:.{3}f}mm"

    def get_z_pos_str(self) -> str:
        """
        Get the Z-axis position as a formatted string.

        Returns:
            str: The Z-axis position as a formatted string.
        """
        if not self.enabled: return "?"
        return f"{(self.motor_z.get_position(scale=False) - self.offset_z) / self.mm2steps:.{3}f}mm"
