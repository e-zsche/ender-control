import sys
import time
import logging
import serial
from serial.tools.list_ports import comports
import gscrib

"""
Module for controlling an Ender-3 filament printer.
Based on gscrib, a fairly new GCode python module, which made
implementing this easy-peasy. Outstanding library for this use case.
- source: https://github.com/joansalasoler/gscrib
- docs: https://gscrib.readthedocs.io/en/latest/
"""

class Ender(gscrib.GCodeBuilder):
    """Ender class for controlling Ender-3 Printer via USB-serial.

    Based on the gscrib GCodeBuilder class. Automatically searches and
    opens the correct serial port. If no serial port is found a
    SerialException is raised.

    Automatically sets physical bounds for GCode generation.
    """
    def __init__(self, *args, **kwargs) -> None:
        self._logger = logging.getLogger("ender")
        self._serial_port = self.__find_serial_port()
        if self._serial_port is None:
            raise RuntimeError("ERROR: could not find ender-3 serial port")
        super().__init__(self,
                         direct_write='serial',
                         port=self._serial_port,
                         baudrate=115200,
                         *args, **kwargs)
        # set machine bounds for gcode
        self.set_bounds("bed-temperature", min=0, max=100)
        self.set_bounds("feed-rate", min=50, max=7000)
        self.set_bounds("axes", min=(0, 0, 0), max=(235, 235, 90))
        # init parameters
        self.set_length_units("mm")
        self.set_time_units("s")
        self.absolute_mode()
        # set printer parameters
        """standard printer settings:
        Max feedrates (units/s):
            M203 X500.00 Y500.00 Z5.00 E25.00
        Max Acceleration (units/s2):
            M201 X500.00 Y500.00 Z100.00 E5000.00
        Acceleration (units/s2) (P<print-accel> R<retract-accel> T<travel-accel>):
            M204 P500.00 R500.00 T500.00
        Advanced (B<min_segment_time_us> S<min_feedrate> T<min_travel_feedrate> J<junc_dev>):
            M205 B20000.00 S0.00 T0.00 J0.08
        """
        self.write("M203 X5000 Y5000 Z10.0") # set movement acceleration for G0, G1
        self.write("M204 P1000 T1000") # set movement acceleration for G0, G1

    def use_workpiece_coordinate_system(self, coord_num:int=1,
                                        zero_coords:bool=False):
        if not 1 <= coord_num <= 9:
            self._logger.warning(f"available coordinate systems: 1-9")
            return
        match coord_num:
            case 1:
                gcode_cmd = "G54"
            case 2:
                gcode_cmd = "G55"
            case 3:
                gcode_cmd = "G56"
            case 4:
                gcode_cmd = "G57"
            case 5:
                gcode_cmd = "G58"
            case 6:
                gcode_cmd = "G59"
            case 7:
                gcode_cmd = "G59.1"
            case 8:
                gcode_cmd = "G59.2"
            case 9:
                gcode_cmd = "G59.3"
        self.write(gcode_cmd)
        if zero_coords:
            self.set_axis(x=0, y=0)

    def use_machine_coordinate_system(self):
        self.write("G53")

    def get_position(self) -> list:
        writer = self.get_writer()
        self.query("position")
        x = writer.get_parameter("X")
        y = writer.get_parameter("Y")
        z = writer.get_parameter("Z")
        return [x,y,z]

    def print(self, disconnect:bool=True) -> None:
        if disconnect:
            self.teardown()
        else:
            self.flush()

    def print_from_gcode(self, f_path:str,
                         rapid_feedrate:int=None,
                         move_feedrate:int=None,
                         scale:float=1.0) -> None:
        logger = logging.getLogger("GCode Parsing")
        with open(f_path, "r") as f:
            self.ode_content = f.readlines()
            logger.debug(f"read contents: {f_path}")
        for line in self.ode_content:
            logger.debug(f"processing line: {line}")
            splits = line.split(";")[0].split(" ")
            match splits[0]:
                case "G0":
                    logger.debug("found G0 move")
                    x = None
                    y = None
                    z = None
                    feedrate = rapid_feedrate
                    for coord in splits[1:]:
                        if coord.startswith("X"):
                            x = float(coord.split("X")[1])*scale
                        if coord.startswith("Y"):
                            y = float(coord.split("Y")[1])*scale
                        if coord.startswith("Z"):
                            z = float(coord.split("Z")[1])*scale
                        if coord.startswith("F") and feedrate is None:
                            feedrate = float(coord.split("F")[1])
                    logger.debug(f"coordinates: {(x,y,z)}")
                    if feedrate is None:
                        self.rapid(x=x, y=y, z=z)
                    else:
                        self.rapid(x=x, y=y, z=z, F=feedrate)
                case "G1":
                    logger.debug("found G1 move")
                    x = None
                    y = None
                    z = None
                    feedrate = move_feedrate
                    for coord in splits[1:]:
                        if coord.startswith("X"):
                            x = float(coord.split("X")[1])*scale
                        if coord.startswith("Y"):
                            y = float(coord.split("Y")[1])*scale
                        if coord.startswith("Z"):
                            z = float(coord.split("Z")[1])*scale
                        if coord.startswith("F") and move_feedrate is None:
                            feedrate = float(coord.split("F")[1])
                    logger.debug(f"coordinates: {(x,y,z)}")
                    if feedrate is None:
                        self.move(x=x, y=y, z=z)
                    else:
                        self.move(x=x, y=y, z=z, F=feedrate)

    def __find_serial_port(self) -> str:
        self._logger.debug("start ender serial port search")
        ports = comports()
        for port in ports:
            if sys.platform == "linux" and \
                    not "ttyUSB" in port.device:
                continue
            if port.manufacturer is not None:
                continue
            self._logger.debug(f"trying port: {port.device}")
            ser = serial.Serial(port.device, 115200, timeout=0.5)
            if not ser.isOpen():
                continue
            ser.write(b"M115\r\n")
            time.sleep(0.5)
            response = ser.read_all()
            self._logger.debug(f"port response: {response}")
            ser.close()
            if "Marlin" in response.decode():
                self._logger.info(f"found port: {port.device}")
                return port.device
