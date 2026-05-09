import vgamepad
import asyncio
import threading
from controller import Controller, ControllerInputData, VibrationData
from config import CONFIG, ButtonConfig
import logging

logger = logging.getLogger(__name__)

class VirtualController:
    def __init__(self, player_number: int, on_disconnected_callback=None):
        self.player_number = player_number
        self.controllers = []
        self.on_disconnected_callback = on_disconnected_callback
        self.xb_controller = vgamepad.VX360Gamepad()
        self.xb_controller.register_notification(callback_function=self.vibration_callback)
        self.previous_buttons_left = 0x00000000
        self.previous_buttons_right = 0x00000000
        self.next_vibration_event = None
        
        self.loop = None

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

            xb_btns, lt, rt = buttonsConfig.convert_buttons(buttons)
            self.xb_controller.report.wButtons = xb_btns
            self.xb_controller.left_trigger(255 if lt else 0)
            self.xb_controller.right_trigger(255 if rt else 0)

            if controller.is_joycon_right() and len(self.controllers) == 1:
                self.xb_controller.left_joystick_float(inputData.right_stick[1], -inputData.right_stick[0])
            elif controller.is_joycon_left() and len(self.controllers) == 1:
                self.xb_controller.left_joystick_float(-inputData.left_stick[1], inputData.left_stick[0])
            else:
                if not controller.is_joycon_left(): self.xb_controller.right_joystick_float(inputData.right_stick[0], inputData.right_stick[1])
                if not controller.is_joycon_right(): self.xb_controller.left_joystick_float(inputData.left_stick[0], inputData.left_stick[1])
            self.xb_controller.update()

        controller.set_input_report_callback(input_report_callback)

    def is_single(self): 
        return len(self.controllers) == 1
    
    def is_single_joycon_right(self):
        return self.is_single() and self.controllers[0].is_joycon_right()

    def is_single_joycon_left(self):
        return self.is_single() and self.controllers[0].is_joycon_left()
        
    async def update_leds(self):
        for c in self.controllers: await c.set_leds(self.player_number)
    def add_controller(self, c): self.controllers.append(c)
    
    def start_calibration(self):
        for c in self.controllers:
            if hasattr(c, 'start_calibration'):
                c.start_calibration()
                
    async def disconnect(self):
        for c in list(self.controllers):
            if hasattr(c, 'client') and c.client:
                try:
                    await c.client.disconnect()
                except Exception as e:
                    logger.error(f"Disconnect error: {e}")
            if self.on_disconnected_callback:
                await self.on_disconnected_callback(c)

    def trigger_disconnect(self):
        if self.loop and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(self.disconnect(), self.loop)
        else:
            logger.error("Event loop not found or not running.")

    async def remove_controller(self, controller: Controller) -> bool:
        if controller in self.controllers:
            self.controllers.remove(controller)
            
        if len(self.controllers) == 0:
            if hasattr(self, 'xb_controller') and self.xb_controller is not None:
                try:
                    self.xb_controller.unregister_notification()
                except Exception:
                    pass
                
                del self.xb_controller
                self.xb_controller = None
                
            return True 
        else:
            await self.init_added_controller(self.controllers[0])
            return False
