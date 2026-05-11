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
    return int(max(0, min(255, round(val * 127.5 + 128))))



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
        self.touch_tracking_id = 0
        self.was_touching = False
        
        self.mode = getattr(CONFIG, "simulation_mode", "Xbox")
        self._setup_vg_controller()
        
        self.state_lock = threading.Lock()
        self.running = True
        self.update_thread = threading.Thread(target=self._1000hz_loop, daemon=True)
        self.update_thread.start()

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
            
            if self.vg_controller is None:
                return
            
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
        with self.state_lock:
            self._update_as_ps4_locked(inputData, buttons, controller)

    def _update_as_ps4_locked(self, inputData: ControllerInputData, buttons: int, controller: Controller):
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
        if buttons & SWITCH_BUTTONS.get("HOME", 0): 
            report.bSpecial |= DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_PS

        capt = bool(buttons & SWITCH_BUTTONS.get("CAPT", 0))
        tpad_l = bool(buttons & SWITCH_BUTTONS.get("PSTPAD_L", 0))
        tpad_r = bool(buttons & SWITCH_BUTTONS.get("PSTPAD_R", 0))

        is_touching = capt or tpad_l or tpad_r

        if is_touching:
            report.bSpecial |= DS4_SPECIAL_BUTTONS.DS4_SPECIAL_BUTTON_TOUCHPAD
            if not getattr(self, 'was_touching', False):
                self.touch_tracking_id = (getattr(self, 'touch_tracking_id', 0) + 1) & 0x7F
            report.sCurrentTouch.bIsUpTrackingNum1 = self.touch_tracking_id

            if tpad_l:
                report.sCurrentTouch.bTouchData1[0] = 0xE0
                report.sCurrentTouch.bTouchData1[1] = 0x71
                report.sCurrentTouch.bTouchData1[2] = 0x1D
            elif tpad_r:
                report.sCurrentTouch.bTouchData1[0] = 0xA0
                report.sCurrentTouch.bTouchData1[1] = 0x75
                report.sCurrentTouch.bTouchData1[2] = 0x1D
            else:
                report.sCurrentTouch.bTouchData1[0] = 0xC0
                report.sCurrentTouch.bTouchData1[1] = 0x73
                report.sCurrentTouch.bTouchData1[2] = 0x1D
        else:
            report.sCurrentTouch.bIsUpTrackingNum1 = 0x80 | getattr(self, 'touch_tracking_id', 0)

        self.was_touching = is_touching
        report.sCurrentTouch.bIsUpTrackingNum2 = 0x80

        report.bTriggerL = 255 if (buttons & SWITCH_BUTTONS["ZL"]) else 0
        report.bTriggerR = 255 if (buttons & SWITCH_BUTTONS["ZR"]) else 0
        report.bBatteryLvl = 0xAF
        report.bBatteryLvlSpecial = 0x08

        if not hasattr(self, 'last_lx'):
            self.last_lx = 128; self.last_ly = 128
            self.last_rx = 128; self.last_ry = 128
            self.last_gx = 0; self.last_gy = 0; self.last_gz = 0
            self.last_ax = 0; self.last_ay = 0; self.last_az = 0

        if len(self.controllers) == 1:
            if controller.is_joycon_right():
                self.last_lx = float_to_byte(inputData.right_stick[1])
                self.last_ly = float_to_byte(inputData.right_stick[0]) 
            elif controller.is_joycon_left():
                self.last_lx = float_to_byte(-inputData.left_stick[1])
                self.last_ly = float_to_byte(-inputData.left_stick[0]) 
            else:
                self.last_lx = float_to_byte(inputData.left_stick[0])
                self.last_ly = float_to_byte(-inputData.left_stick[1])
                self.last_rx = float_to_byte(inputData.right_stick[0])
                self.last_ry = float_to_byte(-inputData.right_stick[1])
            
            self.last_gx = inputData.gyroscope[0]
            self.last_gy = inputData.gyroscope[2]
            self.last_gz = -inputData.gyroscope[1]
            self.last_ax = inputData.accelerometer[0]
            self.last_ay = inputData.accelerometer[2]
            self.last_az = -inputData.accelerometer[1]
            
        else:
            if controller.is_joycon_left():
                self.last_lx = float_to_byte(inputData.left_stick[0])
                self.last_ly = float_to_byte(-inputData.left_stick[1])
            elif controller.is_joycon_right():
                self.last_rx = float_to_byte(inputData.right_stick[0])
                self.last_ry = float_to_byte(-inputData.right_stick[1])
                self.last_gx = inputData.gyroscope[0]
                self.last_gy = inputData.gyroscope[2]
                self.last_gz = -inputData.gyroscope[1]
                self.last_ax = inputData.accelerometer[0]
                self.last_ay = inputData.accelerometer[2]
                self.last_az = -inputData.accelerometer[1]

        report.bThumbLX = self.last_lx
        report.bThumbLY = self.last_ly
        report.bThumbRX = self.last_rx
        report.bThumbRY = self.last_ry

        def clamp_short(val): return max(-32768, min(32767, int(val)))
        report.wGyroX = clamp_short(self.last_gx)
        report.wGyroY = clamp_short(self.last_gy)
        report.wGyroZ = clamp_short(self.last_gz)
        report.wAccelX = clamp_short(self.last_ax)
        report.wAccelY = clamp_short(self.last_ay)
        report.wAccelZ = clamp_short(self.last_az)

    def update_as_xbox(self, inputData: ControllerInputData, buttons: int, controller: Controller, buttonsConfig: ButtonConfig):
        with self.state_lock:
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

    def _1000hz_loop(self):
        import time
        last_time = time.perf_counter()
        while self.running:
            now = time.perf_counter()
            dt = now - last_time
            if dt < 0.001:
                time.sleep(0)
                continue
                
            last_time = now
            if dt > 0.05: dt = 0.015
            
            with self.state_lock:
                if self.vg_controller is None:
                    continue
                    
                if self.mode == "PS4":
                    ticks = int(dt * 187500)
                    self.ds4_timestamp = (getattr(self, 'ds4_timestamp', 0) + ticks) & 0xFFFF
                    
                    self.report_ex.Report.wTimestamp = self.ds4_timestamp
                    self.report_ex.Report.bTouchPacketsN = 1
                    self.touch_packet_counter = (getattr(self, 'touch_packet_counter', 0) + 1) & 0xFF
                    self.report_ex.Report.sCurrentTouch.bPacketCounter = self.touch_packet_counter
            
                    try:
                        import vgamepad.win.vigem_client as vcli
                        vcli.vigem_target_ds4_update_ex_ptr.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(DS4_REPORT_EX)]
                        busp = self.vg_controller.vbus.get_busp()
                        devicep = self.vg_controller._devicep
                        vcli.vigem_target_ds4_update_ex_ptr(busp, devicep, ctypes.byref(self.report_ex))
                    except Exception as e:
                        self.vg_controller.update()
                else:
                    self.vg_controller.update()
                
    async def disconnect(self):
        self.running = False
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
            
        disconnect_tasks = []
        for c in list(self.controllers):
            if hasattr(c, 'client') and c.client and c.client.is_connected:
                disconnect_tasks.append(asyncio.create_task(c.disconnect()))
                
        if disconnect_tasks:
            await asyncio.gather(*disconnect_tasks)
            
        for c in list(self.controllers):
            if self.on_disconnected_callback:
                await self.on_disconnected_callback(c)
                
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
            if getattr(self, 'running', True):
                await self.init_added_controller(self.controllers[0])
            return False
