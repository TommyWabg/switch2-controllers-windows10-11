import bleak
from bleak import BleakScanner, BleakClient, BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
import asyncio
import logging
import bluetooth
import win32api
import win32con
from dataclasses import dataclass
import ctypes
import time
import threading
try:
    ctypes.windll.winmm.timeBeginPeriod(1)
except Exception:
    pass
from config import CONFIG, SWITCH_BUTTONS
from utils import (
    apply_calibration_to_axis, get_stick_xy, press_or_release_mouse_button, 
    reverse_bits, signed_looping_difference_16bit, to_hex, decodeu, decodes, 
    convert_mac_string_to_value
)

logging.basicConfig()
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Controller identification info
NINTENDO_VENDOR_ID = 0x057e
JOYCON2_RIGHT_PID = 0x2066
JOYCON2_LEFT_PID = 0x2067
PRO_CONTROLLER2_PID = 0x2069
NSO_GAMECUBE_CONTROLLER_PID = 0x2073

CONTROLER_NAMES = {
    JOYCON2_RIGHT_PID: "Joy-con 2 (Right)",
    JOYCON2_LEFT_PID: "Joy-con 2 (Left)",
    PRO_CONTROLLER2_PID: "Pro Controller 2",
    NSO_GAMECUBE_CONTROLLER_PID: "NSO Gamecube Controller"
}

# BLE GATT Characteristics UUID
INPUT_REPORT_UUID = "ab7de9be-89fe-49ad-828f-118f09df7fd2"
VIBRATION_WRITE_JOYCON_R_UUID = "fa19b0fb-cd1f-46a7-84a1-bbb09e00c149"
VIBRATION_WRITE_JOYCON_L_UUID = "289326cb-a471-485d-a8f4-240c14f18241"
VIBRATION_WRITE_PRO_CONTROLLER_UUID = "cc483f51-9258-427d-a939-630c31f72b05"

COMMAND_WRITE_UUID = "649d4ac9-8eb7-4e6c-af44-1ea54fe5f005"
COMMAND_RESPONSE_UUID = "c765a961-d9d8-4d36-a20a-5315b111836a"

# Commands and subcommands
COMMAND_LEDS = 0x09
SUBCOMMAND_LEDS_SET_PLAYER = 0x07
COMMAND_VIBRATION = 0x0A
SUBCOMMAND_VIBRATION_PLAY_PRESET = 0x02
COMMAND_MEMORY = 0x02
SUBCOMMAND_MEMORY_READ = 0x04
COMMAND_PAIR = 0x15
SUBCOMMAND_PAIR_SET_MAC = 0x01
SUBCOMMAND_PAIR_LTK1 = 0x04
SUBCOMMAND_PAIR_LTK2 = 0x02
SUBCOMMAND_PAIR_FINISH = 0x03
COMMAND_FEATURE = 0x0c
SUBCOMMAND_FEATURE_INIT = 0x02
SUBCOMMAND_FEATURE_ENABLE = 0x04

FEATURE_MOTION = 0x04
FEATURE_MOUSE = 0x10
FEATURE_MAGNOMETER = 0x80

# Addresses in controller memory
ADDRESS_CONTROLLER_INFO = 0x00013000
CALIBRATION_JOYSTICK_1 = 0x0130A8
CALIBRATION_JOYSTICK_2 = 0x0130E8
CALIBRATION_USER_JOYSTICK_1 = 0x1fc042
CALIBRATION_USER_JOYSTICK_2 = 0x1fc062

LED_PATTERN = {
    1: 0x01, 2: 0x03, 3: 0x07, 4: 0x0F,
    5: 0x09, 6: 0x05, 7: 0x0D, 8: 0x06,
}

### Dataclasses ###

@dataclass
class MouseState:
    x: int
    y: int
    lb: bool
    mb: bool 
    rb: bool

@dataclass
class StickCalibrationData:
    center: tuple[int, int]
    max: tuple[int, int]
    min: tuple[int, int]

    def __init__(self, data: bytes):
        self.center = get_stick_xy(data[0:3])
        self.max = get_stick_xy(data[3:6])
        self.min = get_stick_xy(data[6:9])

    def apply_calibration(self, raw_values: tuple[int, int]):
        return (apply_calibration_to_axis(raw_values[0], self.center[0], self.max[0], self.min[0]), 
                apply_calibration_to_axis(raw_values[1], self.center[1], self.max[1], self.min[1]))

@dataclass
class ControllerInputData:
    raw_data: bytes
    time: int
    buttons: int
    left_stick: tuple[int, int]
    right_stick: tuple[int, int]
    mouse_coords: tuple[int, int]
    mouse_roughness: int
    mouse_distance: int
    magnometer: tuple[int, int, int]
    battery_voltage: float
    battery_current: float
    temperature: float
    accelerometer: tuple[int, int, int]
    gyroscope: tuple[int, int, int]

    def __init__(self, data: bytes, left_stick_calibration: StickCalibrationData, right_stick_calibration: StickCalibrationData):
        self.raw_data = data
        self.time = decodeu(data[0:4])
        self.buttons = decodeu(data[4:8])
        self.left_stick = get_stick_xy(data[10:13])
        self.right_stick = get_stick_xy(data[13:16])
        self.mouse_coords = decodeu(data[16:18]), decodeu(data[18:20])
        self.mouse_roughness = decodeu(data[20:22])
        self.mouse_distance = decodeu(data[22:24])
        self.magnometer = decodes(data[25:27]), decodes(data[27:29]), decodes(data[29:31])
        self.battery_voltage = decodeu(data[31:33]) / 1000.0
        self.battery_current = decodeu(data[33:35]) / 100.0
        self.temperature = 25 + decodeu(data[46:48]) / 127.0
        self.accelerometer = decodes(data[48:50]), decodes(data[50:52]), decodes(data[52:54])
        self.gyroscope = decodes(data[54:56]), decodes(data[56:58]), decodes(data[58:60])

        if left_stick_calibration:
            self.left_stick = left_stick_calibration.apply_calibration(self.left_stick)
        if right_stick_calibration:
            self.right_stick = right_stick_calibration.apply_calibration(self.right_stick)
            
    

@dataclass
class ControllerInfo:
    serial_number: str
    vendor_id: int
    product_id: int
    color1: bytes
    color2: bytes
    color3: bytes
    color4: bytes

    def __init__(self, data: bytes):
        self.serial_number = data[2:16].decode()
        self.vendor_id = decodeu(data[18:20])
        self.product_id = decodeu(data[20:22])
        self.color1 = data[25:28]
        self.color2 = data[28:31]
        self.color3 = data[31:34]
        self.color4 = data[34:37]

@dataclass
class VibrationData:
    lf_freq: int = 0x0e1
    lf_en_tone: bool = False
    lf_amp: int = 0x000
    hf_freq: int = 0x1e1
    hf_en_tone : int = False
    hf_amp: int = 0x000

    def get_bytes(self):
        value = 0x0000000000
        value |= (self.lf_freq & 0x1FF)        
        value |= int(self.lf_en_tone) << 9     
        value |= (self.lf_amp & 0x3FF) << 10   
        value |= (self.hf_freq & 0x1FF) << 20  
        value |= int(self.hf_en_tone) << 29    
        value |= (self.hf_amp & 0x3FF) << 30   
        return value.to_bytes(byteorder='little', length=5)

class Controller:
    
    def __init__(self, device: BLEDevice):
        self.device: BLEDevice = device
        self.client: BleakClient = None
        self.controller_info: ControllerInfo = None
        self.input_report_callback = None
        self.disconnected_callback = None
        self.left_stick_calibration: StickCalibrationData = None
        self.right_stick_calibration: StickCalibrationData = None
        self.previous_mouse_state: MouseState = None

        self.side_buttons_pressed = False
        self.response_future = None
        self.vibration_packet_id = 0
        self.battery_voltage = None
        
        self.gyro_mouse_enabled = False
        self.gr_was_pressed = False
        self.prev_zr = False
        self.prev_zl = False
        
        self.residual_x = 0.0
        self.residual_y = 0.0
        self.smooth_dx = 0.0
        self.smooth_dy = 0.0
        
        self.prev_screenshot = False
        self.prev_key_c = False
        
        self.gyro_target_vx = 0.0
        self.gyro_target_vy = 0.0
        self.jc_target_vx = 0.0    
        self.jc_target_vy = 0.0    
        self.jc_mouse_active = False
        self.current_vx = 0.0
        self.current_vy = 0.0
        self.interp_residual_x = 0.0
        self.interp_residual_y = 0.0
        self.interp_task = None
        
        self.is_calibrating = False
        self.calibration_end_time = 0
        
        # Set defaults, will load actual calibration offsets after connecting and getting device info
        self.gyro_bias = (0.0, 0.0, 0.0)
            
        self.stick_r_bias = tuple(getattr(CONFIG, "stick_r_bias", [0.0, 0.0]))
        self.calibration_samples_gyro = []
        self.calibration_samples_stick = []
        
    def __repr__(self):
        return f"{CONTROLER_NAMES[self.controller_info.product_id]} : {self.device.address}"

    def start_calibration(self):
        self.is_calibrating = True
        self.calibration_end_time = time.perf_counter() + 2.0
        self.calibration_samples_gyro = []
        self.calibration_samples_stick = []
        
        logger.info(f"Calibration started for {self.device.address}. Please keep the controller stationary...")
    
    async def connect(self):
        if (self.client is not None):
            raise Exception("Already connected")
        
        def disconnected_callback(client: BleakClient):
            if (self.disconnected_callback is not None):
                asyncio.create_task(self.disconnected_callback(self))
        
        self.client = BleakClient(self.device, disconnected_callback=disconnected_callback)
        await self.client.connect(timeout=20.0)
        
        logger.info(f"Connected to {self.device.address}")
        
        import sys
        if sys.platform == "win32":
            try:
                try:
                    import winrt.windows.devices.bluetooth as wd_bluetooth
                except ImportError:
                    import bleak_winrt.windows.devices.bluetooth as wd_bluetooth
                    
                if hasattr(wd_bluetooth, 'BluetoothLEPreferredConnectionParameters'):
                    params = wd_bluetooth.BluetoothLEPreferredConnectionParameters.throughput_optimized
                    device = getattr(self.client._backend, "_requester", None)
                    if device:
                        if hasattr(device, 'request_preferred_connection_parameters_async'):
                            await device.request_preferred_connection_parameters_async(params)
                        elif hasattr(device, 'request_preferred_connection_parameters'):
                            device.request_preferred_connection_parameters(params)
                        logger.info(f"ThroughputOptimized applied for {self.device.address}")
                else:
                    logger.info("ThroughputOptimized not available on this Windows version.")
            except Exception as e:
                logger.warning(f"Failed to apply ThroughputOptimized: {e}")

        await asyncio.sleep(1.0)
        
        self.response_future = None
        def command_response_callback(sender: BleakGATTCharacteristic, data: bytearray):
            if self.response_future:
                self.response_future.set_result(data)
        
        for attempt in range(3):
            try:
                await self.client.start_notify(COMMAND_RESPONSE_UUID, command_response_callback)
                break
            except Exception as e:
                if attempt == 2: raise
                logger.warning(f"Notify failed, retry {attempt+1}: {e}")
                await asyncio.sleep(1.0)

        self.controller_info = await self.read_controller_info()
        
        # After getting controller info, prioritize loading specific calibration from MAC address
        addr = self.device.address
        if addr in CONFIG.calibration_data:
            self.gyro_bias = tuple(CONFIG.calibration_data[addr])
            logger.info(f"Loaded per-device calibration for {addr}")
        elif self.is_joycon_left():
            self.gyro_bias = tuple(getattr(CONFIG, "gyro_bias_l", [0.0, 0.0, 0.0]))
        else:
            self.gyro_bias = tuple(getattr(CONFIG, "gyro_bias_r", [0.0, 0.0, 0.0]))
        self.stick_calibration, self.second_stick_calibration = await self.read_calibration_data()

        await self.enable_input_notify_callback()
        
        await self.enableFeatures(FEATURE_MOTION | FEATURE_MOUSE)

        self.interp_running = True
        self.interp_thread = threading.Thread(target=self._interpolation_thread_loop, daemon=True)
        self.interp_thread.start()

        logger.info(f"Successfully initialized {self.device.address} : {self.controller_info}")
        try:
            bass_thump = VibrationData(lf_freq=0x060, lf_amp=0x350, hf_freq=0x0c0, hf_amp=0x250)
            sharp_click = VibrationData(hf_freq=0x1e2, hf_amp=0x300, lf_amp=0x030)
            stop_vibration = VibrationData() 

            await self.set_vibration(bass_thump)
            await asyncio.sleep(0.2) 
            
            await self.set_vibration(stop_vibration)
            await asyncio.sleep(0.01) 
            
            await self.set_vibration(sharp_click)
            await asyncio.sleep(1) 
            
            await self.set_vibration(stop_vibration)
            logger.info("Connection haptic feedback triggered.")
        except Exception as e:
            logger.warning(f"Failed to trigger haptic feedback: {e}")

    @classmethod
    async def create_from_device(cls, device: BLEDevice):
        controller = cls(device)
        await controller.connect()
        return controller
    
    @classmethod
    async def create_from_mac_address(cls, mac_address):
        device = await BleakScanner.find_device_by_address(mac_address)
        return await cls.create_from_device(device)
        
    async def disconnect(self):
        self.interp_running = False
        if self.client:
            if self.client.is_connected:
                logger.info(f"Disconnecting Bluetooth from {self.device.address}...")
                try:
                    await asyncio.wait_for(self.client.disconnect(), timeout=1.5)
                except Exception:
                    pass
            self.client = None

    ### Commands & Features ###

    async def write_command(self, command_id: int, subcommand_id: int, command_data = b''):
        command_buffer = command_id.to_bytes() + b"\x91\x01" + subcommand_id.to_bytes() + b"\x00" + len(command_data).to_bytes() + b"\x00\x00" + command_data
        self.response_future = asyncio.get_running_loop().create_future()
        await self.client.write_gatt_char(COMMAND_WRITE_UUID, command_buffer)
        response_buffer = await self.response_future
        if len(response_buffer) < 8 or response_buffer[0] != command_id or response_buffer[1] != 0x01:
            raise Exception(f"Unexpected response : {response_buffer}")
        return response_buffer[8:]

    async def enableFeatures(self, feature_flags: int):
        await self.write_command(COMMAND_FEATURE, SUBCOMMAND_FEATURE_INIT, feature_flags.to_bytes().ljust(4, b'\0'))
        await self.write_command(COMMAND_FEATURE, SUBCOMMAND_FEATURE_ENABLE, feature_flags.to_bytes().ljust(4, b'\0'))

    async def set_vibration(self, vibration: VibrationData, vibration2 = VibrationData(), vibration3 = VibrationData()):
        motor_vibrations = (0x50 + (self.vibration_packet_id & 0x0F)).to_bytes() + vibration.get_bytes() + vibration2.get_bytes() + vibration3.get_bytes()
        if self.is_joycon_left():
            await self.client.write_gatt_char(VIBRATION_WRITE_JOYCON_L_UUID, (b'\x00' + motor_vibrations))
        elif self.is_joycon_right():
            await self.client.write_gatt_char(VIBRATION_WRITE_JOYCON_R_UUID, (b'\x00' + motor_vibrations))
        elif self.is_pro_controller():
            await self.client.write_gatt_char(VIBRATION_WRITE_PRO_CONTROLLER_UUID, (b'\x00' + motor_vibrations + motor_vibrations))
        self.vibration_packet_id += 1

    async def set_leds(self, player_number: int, reversed=False):
        if player_number > 8: player_number = 8
        value = LED_PATTERN[player_number]
        if reversed: value = reverse_bits(value, 4)
        data = value.to_bytes().ljust(4, b'\0')
        await self.write_command(COMMAND_LEDS, SUBCOMMAND_LEDS_SET_PLAYER, data)

    async def play_vibration_preset(self, preset_id: int):
        await self.write_command(COMMAND_VIBRATION, SUBCOMMAND_VIBRATION_PLAY_PRESET, preset_id.to_bytes().ljust(4, b'\0'))

    async def read_memory(self, length: int, address: int):
        if length > 0x4F: raise Exception("Maximum read size is 0x4F bytes")
        data = await self.write_command(COMMAND_MEMORY, SUBCOMMAND_MEMORY_READ, length.to_bytes() + b'\x7e\0\0' + address.to_bytes(length=4,byteorder='little'))
        if (data[0] != length or decodeu(data[4:8]) != address):
            raise Exception(f"Unexpected response from read commmand : {data}")
        return data[8:]

    async def read_controller_info(self):
        info = await self.read_memory(0x40, ADDRESS_CONTROLLER_INFO)
        return ControllerInfo(info)

    async def read_calibration_data(self):
        calibration_data_1 = await self.read_memory(0x0b, CALIBRATION_USER_JOYSTICK_1)
        if (decodeu(calibration_data_1[:3]) == 0xFFFFFF):
            calibration_data_1 = await self.read_memory(0x0b, CALIBRATION_JOYSTICK_1)
        calibration_data_2 = await self.read_memory(0x0b, CALIBRATION_USER_JOYSTICK_2)
        if (decodeu(calibration_data_2[:3]) == 0xFFFFFF):
            calibration_data_2 = await self.read_memory(0x0b, CALIBRATION_JOYSTICK_2)

        if self.is_joycon_left():
            return StickCalibrationData(calibration_data_1), None
        if self.is_joycon_right():
            return None, StickCalibrationData(calibration_data_1)
        return StickCalibrationData(calibration_data_1), StickCalibrationData(calibration_data_2)

    async def pair(self):
        mac_value = convert_mac_string_to_value(bluetooth.read_local_bdaddr()[0])
        await self.write_command(COMMAND_PAIR, SUBCOMMAND_PAIR_SET_MAC,b"\x00\x02" +  mac_value.to_bytes(6, 'little') + mac_value.to_bytes(6, 'little'))
        ltk1 = bytes([0x00, 0xea, 0xbd, 0x47, 0x13, 0x89, 0x35, 0x42, 0xc6, 0x79, 0xee, 0x07, 0xf2, 0x53, 0x2c, 0x6c, 0x31])
        await self.write_command(COMMAND_PAIR, SUBCOMMAND_PAIR_LTK1, ltk1)
        ltk2 = bytes([0x00, 0x40, 0xb0, 0x8a, 0x5f, 0xcd, 0x1f, 0x9b, 0x41, 0x12, 0x5c, 0xac, 0xc6, 0x3f, 0x38, 0xa0, 0x73])
        await self.write_command(COMMAND_PAIR, SUBCOMMAND_PAIR_LTK2, ltk2)
        await self.write_command(COMMAND_PAIR, SUBCOMMAND_PAIR_FINISH, b'\0')

    async def enable_input_notify_callback(self):
        def input_report_callback(sender, data):
            inputData = ControllerInputData(data, self.stick_calibration, self.second_stick_calibration)
            self.battery_voltage = inputData.battery_voltage

            btn_states = {
                "GL": bool(inputData.buttons & 0x02000000),
                "GR": bool(inputData.buttons & 0x01000000),
                "C":  bool(inputData.buttons & 0x00004000),
                "CAPT": bool(inputData.buttons & 0x00002000),
                "SL_R": bool(inputData.buttons & 0x00000020),
                "SR_L": bool(inputData.buttons & 0x00100000) 
            }

            inputData.buttons &= ~(0x03106020)

            trigger_gyro = False
            trigger_screenshot = btn_states["CAPT"]
            trigger_key_c = False

            mapping_pairs = [
                (btn_states["GL"], getattr(CONFIG, "gl_mapping", "None")),
                (btn_states["GR"], getattr(CONFIG, "gr_mapping", "None")),
                (btn_states["C"],  getattr(CONFIG, "c_mapping", "None")),
                (btn_states["SL_R"], getattr(CONFIG, "slr_mapping", "None")),
                (btn_states["SR_L"], getattr(CONFIG, "srl_mapping", "None"))
            ]

            for is_pressed, action in mapping_pairs:
                if is_pressed:
                    if action == "Gyro": trigger_gyro = True
                    elif action == "CAPT": trigger_screenshot = True
                    elif action == "C": trigger_key_c = True
                    elif action in SWITCH_BUTTONS:
                        inputData.buttons |= SWITCH_BUTTONS[action]

            raw_left_pressed  = bool(inputData.buttons & 0x01)
            raw_up_pressed    = bool(inputData.buttons & 0x02)
            raw_down_pressed  = bool(inputData.buttons & 0x04)
            raw_right_pressed = bool(inputData.buttons & 0x08)
            inputData.buttons &= ~0x0F
            
            abxy_mode = getattr(CONFIG, "abxy_mode", "Xbox")
            if abxy_mode == "Switch":
                if raw_down_pressed:  inputData.buttons |= 0x08
                if raw_right_pressed: inputData.buttons |= 0x04
                if raw_left_pressed:  inputData.buttons |= 0x02
                if raw_up_pressed:    inputData.buttons |= 0x01
            else:
                if raw_right_pressed: inputData.buttons |= 0x08
                if raw_down_pressed:  inputData.buttons |= 0x04
                if raw_up_pressed:    inputData.buttons |= 0x02
                if raw_left_pressed:  inputData.buttons |= 0x01

            if trigger_screenshot and not getattr(self, 'prev_screenshot', False):
                win32api.keybd_event(0x5B, 0, 0, 0)
                win32api.keybd_event(0x2C, 0, 0, 0)
            elif not trigger_screenshot and getattr(self, 'prev_screenshot', False):
                win32api.keybd_event(0x2C, 0, win32con.KEYEVENTF_KEYUP, 0)
                win32api.keybd_event(0x5B, 0, win32con.KEYEVENTF_KEYUP, 0)
            self.prev_screenshot = trigger_screenshot

            if trigger_key_c and not getattr(self, 'prev_key_c', False):
                win32api.keybd_event(0x43, 0, 0, 0)
            elif not trigger_key_c and getattr(self, 'prev_key_c', False):
                win32api.keybd_event(0x43, 0, win32con.KEYEVENTF_KEYUP, 0)
            self.prev_key_c = trigger_key_c

            if inputData.buttons & (SWITCH_BUTTONS.get("SR_R", 0) | SWITCH_BUTTONS.get("SL_R", 0) | SWITCH_BUTTONS.get("SL_L", 0) | SWITCH_BUTTONS.get("SR_L", 0)):
                self.side_buttons_pressed = True

            if getattr(self, 'is_calibrating', False):
                self.simulate_gyro_mouse(inputData, False)
            else:
                self.simulate_mouse(inputData)
                # Record own trigger state and use shared trigger (for combined mode cross-controller activation)
                self._own_gyro_trigger = trigger_gyro
                self._own_zr_pressed = bool(inputData.buttons & SWITCH_BUTTONS.get("ZR", 0))
                self._own_zl_pressed = bool(inputData.buttons & SWITCH_BUTTONS.get("ZL", 0))
                
                effective_gyro_trigger = trigger_gyro or getattr(self, '_shared_gyro_trigger', False)
                effective_zr = self._own_zr_pressed or getattr(self, '_shared_zr_pressed', False)
                effective_zl = self._own_zl_pressed or getattr(self, '_shared_zl_pressed', False)
                
                self.simulate_gyro_mouse(inputData, effective_gyro_trigger, effective_zr, effective_zl)

            if self.input_report_callback is not None:
                self.input_report_callback(inputData, self)

        await self.client.start_notify(INPUT_REPORT_UUID, input_report_callback)

    def set_input_report_callback(self, callback):
        self.input_report_callback = callback
        
    def simulate_mouse(self, inputData: ControllerInputData):
        mouse_config = CONFIG.mouse_config
        
        if mouse_config.enabled and self.is_joycon():
            self.jc_mouse_active = True 
            
            if inputData.mouse_distance != 0 and inputData.mouse_distance < 1000 and inputData.mouse_roughness < 4000:
                x, y = inputData.mouse_coords
                mouseButtonsConfig = mouse_config.joycon_l_buttons if self.is_joycon_left() else mouse_config.joycon_r_buttons
                lb = inputData.buttons & mouseButtonsConfig.left_button
                mb = inputData.buttons & mouseButtonsConfig.middle_button
                rb = inputData.buttons & mouseButtonsConfig.right_button
                
                inputData.buttons &= ~(mouseButtonsConfig.left_button | mouseButtonsConfig.middle_button | mouseButtonsConfig.right_button)

                if getattr(self, 'previous_mouse_state', None) is not None:
                    dx = signed_looping_difference_16bit(self.previous_mouse_state.x, x)
                    dy = signed_looping_difference_16bit(self.previous_mouse_state.y ,y)

                    if dx != 0 or dy != 0:
                        self.jc_target_vx = dx * mouse_config.sensitivity * 0.009
                        self.jc_target_vy = dy * mouse_config.sensitivity * 0.009
                    else:
                        self.jc_target_vx = 0.0
                        self.jc_target_vy = 0.0

                    mx, my = win32api.GetCursorPos()
                    press_or_release_mouse_button(lb, self.previous_mouse_state.lb, win32con.MOUSEEVENTF_LEFTDOWN, mx, my)
                    press_or_release_mouse_button(mb, self.previous_mouse_state.mb, win32con.MOUSEEVENTF_MIDDLEDOWN, mx, my)
                    press_or_release_mouse_button(rb, self.previous_mouse_state.rb, win32con.MOUSEEVENTF_RIGHTDOWN, mx, my)

                    if self.is_joycon_right():
                        scroll_value = inputData.right_stick[1]
                        inputData.right_stick = 0,0
                    else:
                        scroll_value = inputData.left_stick[1]
                        inputData.left_stick = 0,0

                    if abs(scroll_value) > 0.2:
                        win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, int(scroll_value * 60 * mouse_config.scroll_sensitivity), 0)
                        
                self.previous_mouse_state = MouseState(x, y, bool(lb), bool(mb), bool(rb))
            else:
                self.previous_mouse_state = None
                self.jc_target_vx = 0.0
                self.jc_target_vy = 0.0
        else:
            self.jc_mouse_active = False
            self.jc_target_vx = 0.0
            self.jc_target_vy = 0.0

    def simulate_gyro_mouse(self, inputData: ControllerInputData, trigger_pressed: bool, zr_pressed: bool, zl_pressed: bool):
        if not getattr(self, 'gyro_active', True):
            # Reset all speed states to prevent drift when switching Gyro sides
            self.gyro_target_vx = 0.0
            self.gyro_target_vy = 0.0
            self.current_vx = 0.0
            self.current_vy = 0.0
            self.interp_residual_x = 0.0
            self.interp_residual_y = 0.0
            self.gyro_mouse_enabled = False
            return

        activation_mode = getattr(CONFIG, "gyro_activation_mode", "Toggle")


        if getattr(self, 'is_calibrating', False):
            if time.perf_counter() < self.calibration_end_time:
                self.calibration_samples_gyro.append(inputData.gyroscope)
                # Ensure ALL output variables are zeroed during calibration to stop leakage
                inputData.left_stick = (0.0, 0.0)
                inputData.right_stick = (0.0, 0.0)
                inputData.gyroscope = (0.0, 0.0, 0.0)
                inputData.accelerometer = (0.0, 0.0, 0.0)
                return
            else:
                self.is_calibrating = False

                if len(self.calibration_samples_gyro) > 0:
                    gx = sum(s[0] for s in self.calibration_samples_gyro) / len(self.calibration_samples_gyro)
                    gy = sum(s[1] for s in self.calibration_samples_gyro) / len(self.calibration_samples_gyro)
                    gz = sum(s[2] for s in self.calibration_samples_gyro) / len(self.calibration_samples_gyro)
                    self.gyro_bias = (gx, gy, gz)
                    
                    logger.info(f"Calibration complete for {self.device.address}. Gyro bias: ({gx:.1f}, {gy:.1f}, {gz:.1f})")
                    
                    # Store device-specific calibration data
                    CONFIG.calibration_data[self.device.address] = list(self.gyro_bias)
                    
                    if self.is_joycon_left():
                        CONFIG.gyro_bias_l = list(self.gyro_bias)
                    else:
                        CONFIG.gyro_bias_r = list(self.gyro_bias)
                    CONFIG.save_config()

        bias_threshold = 5  
        bx, by, bz = self.gyro_bias
        # Ignore if bias is extremely small
        bx = bx if abs(bx) > bias_threshold else 0.0
        by = by if abs(by) > bias_threshold else 0.0
        bz = bz if abs(bz) > bias_threshold else 0.0
        
        raw_gx, raw_gy, raw_gz = inputData.gyroscope
        gyro_x = raw_gx - bx
        gyro_y = raw_gy - by
        gyro_z = raw_gz - bz

        soft_dz = 8.0  
        def apply_soft_deadzone(val, dz):
            if abs(val) < dz: return 0.0
            return (val - dz) if val > 0 else (val + dz)

        gyro_x = apply_soft_deadzone(gyro_x, soft_dz)
        gyro_y = apply_soft_deadzone(gyro_y, soft_dz)
        gyro_z = apply_soft_deadzone(gyro_z, soft_dz)

        inputData.gyroscope = (gyro_x, gyro_y, gyro_z)
        
        rx, ry = inputData.right_stick

        if activation_mode == "Hold":
            self.gyro_mouse_enabled = trigger_pressed
        else:
            if trigger_pressed and not self.gr_was_pressed:
                self.gyro_mouse_enabled = not self.gyro_mouse_enabled
                
        self.gr_was_pressed = trigger_pressed

        if self.gyro_mouse_enabled:
            if self.is_joycon_left():
                rx, ry = inputData.left_stick
                inputData.left_stick = (0, 0)
            else:
                rx, ry = inputData.right_stick
                inputData.right_stick = (0, 0)
            
            target_vx = 0.0
            target_vy = 0.0
            
            gyro_x, gyro_y, gyro_z = inputData.gyroscope
            gyro_deadzone = 0.2 
            
            current_mode = getattr(CONFIG, "gyro_mode", "Yaw")

            if current_mode == "Roll":
                ax, ay, az = inputData.accelerometer
                
                tilt_normalized = ax / 4000.0  
                
                sensitivity = getattr(CONFIG, "gyro_sensitivity", 4.0)
                steer_value = tilt_normalized * (sensitivity * -2)
                
                steer_value = max(-1.0, min(1.0, steer_value))
                
                inputData.left_stick = (steer_value, inputData.left_stick[1])

            else:
                if abs(gyro_x) > gyro_deadzone or abs(gyro_z) > gyro_deadzone or abs(gyro_y) > gyro_deadzone:
                    sensitivity = getattr(CONFIG, "gyro_sensitivity", 0.3)
                    horizontal_val = -gyro_z
                    
                    eff_h = 0
                    if horizontal_val > gyro_deadzone: eff_h = horizontal_val - gyro_deadzone
                    elif horizontal_val < -gyro_deadzone: eff_h = horizontal_val + gyro_deadzone
                        
                    hold_mode = getattr(self, "hold_mode", "Horizontal")
                    if self.is_pro_controller():
                        vertical_val = gyro_x
                    elif hold_mode == "Vertical":
                        vertical_val = gyro_x
                    elif self.is_joycon_left():
                        vertical_val = -gyro_y  # Left Joycon horizontal Y axis is reversed
                    else:
                        vertical_val = gyro_y

                    eff_v = 0
                    if vertical_val > gyro_deadzone: eff_v = vertical_val - gyro_deadzone
                    elif vertical_val < -gyro_deadzone: eff_v = vertical_val + gyro_deadzone
                    
                    accel_factor = 0.002 
                    
                    target_vx += eff_h * sensitivity * accel_factor
                    target_vy += eff_v * -sensitivity * accel_factor

            stick_deadzone = 0.05 
            stick_sens = getattr(CONFIG, "stick_mouse_sensitivity", 20.0) * 0.66
            
            import math
            stick_magnitude = math.sqrt(rx**2 + ry**2)
            
            if stick_magnitude > stick_deadzone:
                normalized_mag = (stick_magnitude - stick_deadzone) / (1.0 - stick_deadzone)
                
                normalized_rx = (rx / stick_magnitude) * normalized_mag
                normalized_ry = (ry / stick_magnitude) * normalized_mag
                
                target_vx += normalized_rx * stick_sens
                target_vy += normalized_ry * -stick_sens

            self.gyro_target_vx = target_vx
            self.gyro_target_vy = target_vy

            # Gyro Mouse Clicks (Hardcoded to ZR/ZL as requested)
            current_zr = zr_pressed
            current_zl = zl_pressed

            if current_zr and not self.prev_zr: win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            elif not current_zr and self.prev_zr: win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

            if current_zl and not self.prev_zl: win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            elif not current_zl and self.prev_zl: win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)

            self.prev_zr = current_zr
            self.prev_zl = current_zl

        else:
            self.gyro_target_vx = 0.0
            self.gyro_target_vy = 0.0
            if getattr(self, 'prev_zr', False): win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            if getattr(self, 'prev_zl', False): win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
            self.prev_zr = self.prev_zl = False
            self.gyro_residual_x = self.gyro_residual_y = 0.0
            self.current_vx = self.current_vy = 0.0
            self.interp_residual_x = self.interp_residual_y = 0.0

    def _interpolation_thread_loop(self):
        last_time = time.perf_counter()
        while self.interp_running:
            if self.client and self.client.is_connected and (self.gyro_mouse_enabled or getattr(self, 'jc_mouse_active', False)):
                if getattr(self, 'is_calibrating', False):
                    self.current_vx = 0.0
                    self.current_vy = 0.0
                else:
                    self.current_vx = self.gyro_target_vx + getattr(self, 'jc_target_vx', 0.0)
                    self.current_vy = self.gyro_target_vy + getattr(self, 'jc_target_vy', 0.0)

                now = time.perf_counter()
                dt = now - last_time
                last_time = now
                
                if dt > 0.05: dt = 0.015 

                time_scale = dt / 0.001
                step_x = self.current_vx * time_scale
                step_y = self.current_vy * time_scale

                total_dx = step_x + self.interp_residual_x
                total_dy = step_y + self.interp_residual_y

                move_x = int(total_dx)
                move_y = int(total_dy)

                self.interp_residual_x = total_dx - move_x
                self.interp_residual_y = total_dy - move_y

                if move_x != 0 or move_y != 0:
                    win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, move_x, move_y, 0, 0)
            else:
                last_time = time.perf_counter()

            time.sleep(0.001)

    ### Info Helpers ###

    def is_joycon_right(self):
        return self.controller_info.product_id == JOYCON2_RIGHT_PID

    def is_joycon_left(self):
        return self.controller_info.product_id == JOYCON2_LEFT_PID
    
    def is_joycon(self):
        return self.is_joycon_left() or self.is_joycon_right()
    
    def is_pro_controller(self):
        return self.controller_info.product_id == PRO_CONTROLLER2_PID

    def has_second_stick(self):
        return self.controller_info.product_id in [PRO_CONTROLLER2_PID, NSO_GAMECUBE_CONTROLLER_PID]
