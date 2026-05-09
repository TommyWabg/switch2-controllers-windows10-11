import vgamepad
import asyncio
import threading
import ctypes
import logging
from controller import Controller, ControllerInputData, VibrationData
from config import CONFIG, ButtonConfig, SWITCH_BUTTONS

from vigem_commons import DS4_REPORT_EX, DS4_BUTTONS, DS4_DPAD_DIRECTIONS, DS4_SPECIAL_BUTTONS

logger = logging.getLogger(__name__)

def get_ds4_dpad(up, down, left, right):
    if up and right: return DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTHEAST
    if down and right: return DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTHEAST
    if down and left: return DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTHWEST
    if up and left: return DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTHWEST
    if up: return DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NORTH
    if down: return DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_SOUTH
    if left: return DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_WEST
    if right: return DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_EAST
    return DS4_DPAD_DIRECTIONS.DS4_BUTTON_DPAD_NONE

def float_to_byte(val):
    return int(max(0, min(255, (val + 1.0) * 127.5)))



class VirtualController:
    def __init__(self, player_number: int, on_disconnected_callback=None):
        self.player_number = player_number
        self.controllers = []
        self.on_disconnected_callback = on_disconnected_callback
        self.previous_buttons_left = 0x00000000
        self.previous_buttons_right = 0x00000000
        self.next_vibration_event = None
        self.loop = None
        self.vg_controller = None
        
        self.mode = getattr(CONFIG, "simulation_mode", "Xbox")
        self._setup_vg_controller()

    def _setup_vg_controller(self):
        if self.vg_controller is not None:
            try:
                self.vg_controller.unregister_notification()
            except Exception:
                pass
            del self.vg_controller
            self.vg_controller = None

        if self.mode == "PS4":
            self.vg_controller = vgamepad.VDS4Gamepad()
            self.report_ex = DS4_REPORT_EX()
            self.report_ex.Report.bThumbLX = 128
            self.report_ex.Report.bThumbLY = 128
            self.report_ex.Report.bThumbRX = 128
            self.report_ex.Report.bThumbRY = 128
            self.report_ex.Report.bBatteryLvl = 0xAF
            self.report_ex.Report.bBatteryLvlSpecial = 0x08
            self.ds4_timestamp = 0
            logger.info("已切換為虛擬 PS4 控制器")
        else:
            self.vg_controller = vgamepad.VX360Gamepad()
            logger.info("已切換為虛擬 Xbox 360 控制器")

        self.vg_controller.register_notification(callback_function=self.vibration_callback)

    def set_mode(self, new_mode):
        if self.mode != new_mode:
            self.mode = new_mode
            self._setup_vg_controller()
            if self.loop and self.loop.is_running():
                asyncio.run_coroutine_threadsafe(self.update_leds(), self.loop)

    def vibration_callback(self, client, target, large_motor, small_motor, led_number, user_data):
        vibrationData = VibrationData()
        vibrationData.lf_amp = int(800 * large_motor / 256)
        vibrationData.hf_amp = int(800 * small_motor / 256)

        if self.next_vibration_event:
            self.next_vibration_event.set()
        
        self.next_vibration_event = asyncio.Event()
        if large_motor == 0 and small_motor == 0:
            self.next_vibration_event.set()
            return

        stop_event = self.next_vibration_event
        async def send_vibration_task():
            for _ in range(500):
                if stop_event.is_set(): break
                tasks = [c.set_vibration(vibrationData) for c in self.controllers]
                await asyncio.gather(*tasks)
                await asyncio.sleep(0.02)

        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(send_vibration_task(), self.loop)

    async def init_added_controller(self, controller: Controller):
        self.loop = asyncio.get_running_loop()
        await self.update_leds()
        
        def input_report_callback(inputData: ControllerInputData, controller: Controller):
            current_buttons = inputData.buttons 
            if len(self.controllers) == 2:
                buttonsConfig = CONFIG.dual_joycons_config
                if controller.is_joycon_left(): self.previous_buttons_left = current_buttons
                else: self.previous_buttons_right = current_buttons
                buttons = self.previous_buttons_left | self.previous_buttons_right
            else:
                buttons = current_buttons
                if controller.is_joycon_left(): buttonsConfig = CONFIG.single_joycon_l_config
                elif controller.is_joycon_right(): buttonsConfig = CONFIG.single_joycon_r_config
                else: buttonsConfig = CONFIG.procon_config

            if self.mode == "PS4":
                self.update_as_ps4(inputData, buttons, controller)
            else:
                self.update_as_xbox(inputData, buttons, controller, buttonsConfig)

        controller.set_input_report_callback(input_report_callback)

    def update_as_ps4(self, inputData: ControllerInputData, buttons: int, controller: Controller):
        report = self.report_ex.Report
        
        ds4_buttons = 0
        if buttons & SWITCH_BUTTONS["Y"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_SQUARE
        if buttons & SWITCH_BUTTONS["X"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_TRIANGLE
        if buttons & SWITCH_BUTTONS["B"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_CROSS
        if buttons & SWITCH_BUTTONS["A"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_CIRCLE
        if buttons & SWITCH_BUTTONS["L"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_SHOULDER_LEFT
        if buttons & SWITCH_BUTTONS["R"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_SHOULDER_RIGHT
        if buttons & SWITCH_BUTTONS["ZL"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_TRIGGER_LEFT
        if buttons & SWITCH_BUTTONS["ZR"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_TRIGGER_RIGHT
        if buttons & SWITCH_BUTTONS["MINUS"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_SHARE
        if buttons & SWITCH_BUTTONS["PLUS"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_OPTIONS
        if buttons & SWITCH_BUTTONS["L_STK"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_THUMB_LEFT
        if buttons & SWITCH_BUTTONS["R_STK"]: ds4_buttons |= DS4_BUTTONS.DS4_BUTTON_THUMB_RIGHT

        up = bool(buttons & SWITCH_BUTTONS["UP"])
        down = bool(buttons & SWITCH_BUTTONS["DOWN"])
        left = bool(buttons & SWITCH_BUTTONS["LEFT"])
        right = bool(buttons & SWITCH_BUTTONS["RIGHT"])
        report.wButtons = ds4_buttons | get_ds4_dpad(up, down, left, right)

        report.bSpecial = 0
        if buttons & SWITCH_BUTTONS["HOME"]: report.bSpecial |= DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_PS
        if buttons & SWITCH_BUTTONS["CAPT"]: report.bSpecial |= DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_TOUCHPAD

        report.bTriggerL = 255 if (buttons & SWITCH_BUTTONS["ZL"]) else 0
        report.bTriggerR = 255 if (buttons & SWITCH_BUTTONS["ZR"]) else 0
        report.bBatteryLvl = 0x1F
        report.bBatteryLvlSpecial = 0x05
        
        if controller.is_joycon_right() and len(self.controllers) == 1:
            report.bThumbLX = float_to_byte(inputData.right_stick[1])
            report.bThumbLY = float_to_byte(inputData.right_stick[0]) 
        elif controller.is_joycon_left() and len(self.controllers) == 1:
            report.bThumbLX = float_to_byte(-inputData.left_stick[1])
            report.bThumbLY = float_to_byte(-inputData.left_stick[0]) 
        else:
            report.bThumbLX = float_to_byte(inputData.left_stick[0])
            report.bThumbLY = float_to_byte(-inputData.left_stick[1])
            report.bThumbRX = float_to_byte(inputData.right_stick[0])
            report.bThumbRY = float_to_byte(-inputData.right_stick[1])

        self.ds4_timestamp = (self.ds4_timestamp + 188) & 0xFFFF
        report.wTimestamp = self.ds4_timestamp
        report.bTouchPacketsN = 1
        report.sCurrentTouch.bPacketCounter = (self.ds4_timestamp // 188) & 0xFF
        report.sCurrentTouch.bIsUpTrackingNum1 = 0x80
        report.sCurrentTouch.bIsUpTrackingNum2 = 0x80

        def clamp_short(val): return max(-32768, min(32767, int(val)))
        report.wGyroX = clamp_short(inputData.gyroscope[0])
        report.wGyroY = clamp_short(inputData.gyroscope[2])
        report.wGyroZ = clamp_short(-inputData.gyroscope[1])
        report.wAccelX = clamp_short(inputData.accelerometer[0])
        report.wAccelY = clamp_short(inputData.accelerometer[2])
        report.wAccelZ = clamp_short(-inputData.accelerometer[1])

        try:
            import vgamepad.win.vigem_client as vcli
            
            vcli.vigem_target_ds4_update_ex_ptr.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(DS4_REPORT_EX)]
            
            busp = self.vg_controller.vbus.get_busp()
            devicep = self.vg_controller._devicep
            vcli.vigem_target_ds4_update_ex_ptr(busp, devicep, ctypes.byref(self.report_ex))
        except Exception as e:
            logger.error(f"Failed to send DS4 EX report: {e}")
            self.vg_controller.update()

    def update_as_xbox(self, inputData: ControllerInputData, buttons: int, controller: Controller, buttonsConfig: ButtonConfig):
        xb_btns, lt, rt = buttonsConfig.convert_buttons(buttons)
        self.vg_controller.report.wButtons = xb_btns
        self.vg_controller.left_trigger(255 if lt else 0)
        self.vg_controller.right_trigger(255 if rt else 0)

        if controller.is_joycon_right() and len(self.controllers) == 1:
            self.vg_controller.left_joystick_float(inputData.right_stick[1], -inputData.right_stick[0])
        elif controller.is_joycon_left() and len(self.controllers) == 1:
            self.vg_controller.left_joystick_float(-inputData.left_stick[1], inputData.left_stick[0])
        else:
            if not controller.is_joycon_left(): self.vg_controller.right_joystick_float(inputData.right_stick[0], inputData.right_stick[1])
            if not controller.is_joycon_right(): self.vg_controller.left_joystick_float(inputData.left_stick[0], inputData.left_stick[1])
        self.vg_controller.update()

    def is_single(self): 
        return len(self.controllers) == 1
    
    def is_single_joycon_right(self):
        return self.is_single() and self.controllers[0].is_joycon_right()

    def is_single_joycon_left(self):
        return self.is_single() and self.controllers[0].is_joycon_left()
        
    async def update_leds(self):
        for c in self.controllers: await c.set_leds(self.player_number)
        
    def add_controller(self, c): 
        self.controllers.append(c)
    
    def start_calibration(self):
        for c in self.controllers:
            if hasattr(c, 'start_calibration'):
                c.start_calibration()
                
    async def disconnect(self):
        if not self.controllers:
            return

        logger.info(f"玩家 {self.player_number}: 正在關閉虛擬裝置並中斷藍牙連線...")

        if hasattr(self, 'vg_controller') and self.vg_controller is not None:
            try:
                self.vg_controller.unregister_notification()
            except Exception:
                pass
            del self.vg_controller
            self.vg_controller = None
            
        tasks = []
        for c in list(self.controllers):
            if hasattr(c, 'client') and c.client and c.client.is_connected:
                tasks.append(c.disconnect())
            
            if self.on_disconnected_callback:
                await self.on_disconnected_callback(c)
        
        if tasks:
            await asyncio.gather(*tasks)
            
        self.controllers.clear()

    def trigger_disconnect(self):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.disconnect(), self.loop)
        else:
            logger.error("Event loop not found or not running.")

    async def remove_controller(self, controller: Controller) -> bool:
        if controller in self.controllers:
            self.controllers.remove(controller)
            
        if len(self.controllers) == 0:
            if hasattr(self, 'vg_controller') and self.vg_controller is not None:
                try:
                    self.vg_controller.unregister_notification()
                except Exception:
                    pass
                
                del self.vg_controller
                self.vg_controller = None
                
            return True 
        else:
            await self.init_added_controller(self.controllers[0])
            return False
