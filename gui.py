import queue
import threading
import tkinter as tk
from tkinter import ttk
import tkinter.font as tkFont
import yaml
import logging
import asyncio
import os
from controller import Controller
from discoverer import start_discoverer
from config import get_resource, CONFIG, BACK_BUTTON_OPTIONS
from virtual_controller import VirtualController

logger = logging.getLogger(__name__)

controller_frame_size = 200
battery_height = 40

background_color = "#aaaaaa"
block_color = "#404040"
player_number_bg_color = "#8B8B8B"

CONTROLLER_UPDATED_EVENT = '<<ControllersUpdated>>'

class ToggleSwitch(tk.Frame):
    def __init__(self, parent, labels, values, initial_value, command, bg_color):
        super().__init__(parent, bg=bg_color)
        self.labels = labels  
        self.values = values  
        self.command = command
        
        self.btn_left = tk.Button(self, text=labels[0], width=8, font=("Arial", 12, "bold"),
                                  command=lambda: self._on_click(0))
        self.btn_right = tk.Button(self, text=labels[1], width=8, font=("Arial", 12, "bold"),
                                   command=lambda: self._on_click(1))
        
        self.btn_left.pack(side=tk.LEFT)
        self.btn_right.pack(side=tk.LEFT)
        
        self.current_index = 1 if initial_value == values[1] else 0
        self._update_ui()

    def _on_click(self, index):
        if self.current_index != index:
            self.current_index = index
            self._update_ui()
            self.command(self.values[index])

    def _update_ui(self):
        active_style = {"bg": "#D32F2F", "fg": "white", "activebackground": "#ff3333"}
        inactive_style = {"bg": "#d0d0d0", "fg": "black", "activebackground": "#cccccc"}
        
        if self.current_index == 0:
            self.btn_left.config(**active_style)
            self.btn_right.config(**inactive_style)
        else:
            self.btn_left.config(**inactive_style)
            self.btn_right.config(**active_style)
            
    def set_value(self, value):
        self.current_index = 1 if value == self.values[1] else 0
        self._update_ui()

class PlayerInfoBlock:
    def __init__(self, parent):
        self.parent = parent
        self.controller_label = None
        self.player_led_label = None
        self.current_vc = None

        self.load_pictures()
        self.init_interface()

    def init_interface(self):
        self.main_frame = tk.Frame(self.parent, width=controller_frame_size, height=controller_frame_size + 8 + 40, bg=player_number_bg_color)
        self.main_frame.pack(padx=10, pady=10, side=tk.LEFT)
        self.main_frame.pack_propagate(False)

        self.controllers_frame = tk.Frame(self.main_frame, width=controller_frame_size, height=controller_frame_size - battery_height, bg=block_color)
        self.controllers_frame.pack()
        self.controllers_frame.pack_propagate(False)

        self.battery_frame = tk.Frame(self.main_frame, width=controller_frame_size, height=battery_height, bg=block_color, padx=50)
        self.battery_frame.pack()
        self.battery_frame.pack_propagate(False)

    def _on_close_clicked(self):
        if self.current_vc is not None:
            self.close_btn.config(state=tk.DISABLED)
            self.current_vc.trigger_disconnect()

    def load_pictures(self):
        self.joycon2leftandright = tk.PhotoImage(file=get_resource("images/joycon2leftandright.png"))
        self.joycon2right_sideway = tk.PhotoImage(file=get_resource("images/joycon2right_sideway.png"))
        self.joycon2left_sideway = tk.PhotoImage(file=get_resource("images/joycon2left_sideway.png"))
        self.procontroller2 = tk.PhotoImage(file=get_resource("images/procontroller2.png"))
        self.battery_h = tk.PhotoImage(file=get_resource("images/battery_h.png"))
        self.battery_m = tk.PhotoImage(file=get_resource("images/battery_m.png"))
        self.battery_l = tk.PhotoImage(file=get_resource("images/battery_l.png"))
        self.player_leds = {nb: tk.PhotoImage(file=get_resource(f"images/player{nb}.png")) for nb in range(1,5)}

    def clearControllerInfo(self):
        if self.controller_label is not None:
            self.controller_label.destroy()
            self.controller_label = None

        if self.player_led_label is not None:
            self.player_led_label.destroy()
            self.player_led_label = None
            
        if hasattr(self, 'close_btn') and self.close_btn is not None:
            self.close_btn.destroy()
            self.close_btn = None

    def get_image_for_battery_level(self, controller: Controller):
        if controller.battery_voltage is None:
            return self.battery_l
            
        if controller.battery_voltage > 3.25:
            return self.battery_h
        if controller.battery_voltage > 3.125: 
            return self.battery_m
        return self.battery_l

    def displayControllersInfo(self, virtualController : VirtualController):
        self.current_vc = virtualController

        if not virtualController.is_single():
            image = self.joycon2leftandright
        elif virtualController.is_single_joycon_right():
            image = self.joycon2right_sideway
        elif virtualController.is_single_joycon_left():
            image = self.joycon2left_sideway
        else:
            image = self.procontroller2

        self.controller_label = tk.Label(self.controllers_frame, image=image, bg=block_color)
        self.controller_label.pack(fill="none", expand=True)

        self.close_btn = tk.Button(self.controllers_frame, text="✖", bg=block_color, fg="#888888", bd=0, 
                                   font=("Arial", 14, "bold"), activebackground="#ff4444", activeforeground="white", 
                                   command=self._on_close_clicked)
        self.close_btn.place(x=controller_frame_size-30, y=5, width=25, height=25)

        if virtualController.is_single():
            self.battery_label = tk.Label(self.battery_frame, image=self.get_image_for_battery_level(virtualController.controllers[0]), bg=block_color)
            self.battery_label.pack()
        else:
            self.battery_label = tk.Label(self.battery_frame, image=self.get_image_for_battery_level(virtualController.controllers[0]), bg=block_color)
            self.battery_label.pack(side='left')
            self.battery_label2 = tk.Label(self.battery_frame, image=self.get_image_for_battery_level(virtualController.controllers[1]), bg=block_color)
            self.battery_label2.pack(side='right')

        self.player_led_label = tk.Label(self.main_frame, image=self.player_leds[virtualController.player_number], bg=player_number_bg_color)
        self.player_led_label.pack(pady=20)

class ControllerWindow:
    def __init__(self):
        self.root = None
        self.main_frame = None
        self.settings_frame = None
        self.no_controllers = True
        self.message_queue = queue.Queue()
        self.quit_event = threading.Event()
    
    def init_interface(self):
        self.root = tk.Tk()
        photo = tk.PhotoImage(file = get_resource('images/icon.png'))
        self.root.wm_iconphoto(False, photo)
        self.root.title("Switch2 Controllers")
        
        self.root.geometry("1000x580+50+50") 
        self.root.minsize(1000, 640)
        self.root.config(bg=background_color, padx=10, pady=10)
        self.font = tkFont.Font(family="Arial", size=16, weight="bold")
        self.pairing_hint_image = tk.PhotoImage(file=get_resource("images/pairing_hint.png"))

        self.init_settings_panel()
        self.init_gyro_settings_panel()
        self.update([None])
        
    def init_gyro_settings_panel(self):
        self.gyro_frame = tk.LabelFrame(self.root, text=" Gyro Settings ", bg=background_color, font=("Arial", 12, "bold"), padx=10, pady=10)
        self.gyro_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        tk.Label(self.gyro_frame, text="Mode:", bg=background_color, font=("Arial", 12, "bold")).grid(row=0, column=0, padx=5, sticky="e")
        self.gyro_mode_switch = ToggleSwitch(
            self.gyro_frame, 
            labels=["FPS", "Steering"], 
            values=["Yaw", "Roll"], 
            initial_value=CONFIG.gyro_mode, 
            command=self.update_mode_setting, 
            bg_color=background_color
        )
        self.gyro_mode_switch.grid(row=0, column=1, columnspan=2, padx=5, sticky="w")

        tk.Label(self.gyro_frame, text="Sensitivity:", bg=background_color, font=("Arial", 12, "bold")).grid(row=0, column=3, padx=(20, 5), sticky="e")
        self.sens_scale = tk.Scale(self.gyro_frame, from_=1, to=10, resolution=0.2, orient=tk.HORIZONTAL, length=120, bg=background_color, font=("Arial", 12, "bold"), command=self.on_gyro_setting_changed)
        self.sens_scale.set(CONFIG.gyro_sensitivity)
        self.sens_scale.grid(row=0, column=4)
        
        tk.Label(self.gyro_frame, text="Keep controller stationary before calibrating.", bg=background_color, font=("Arial", 12, "bold")).grid(row=0, column=5, columnspan=2, padx=(20, 5), sticky="w")

        tk.Label(self.gyro_frame, text="Activation:", bg=background_color, font=("Arial", 12, "bold")).grid(row=1, column=0, padx=5, pady=(10, 0), sticky="e")
        self.gyro_act_switch = ToggleSwitch(
            self.gyro_frame, 
            labels=["Toggle", "Hold"], 
            values=["Toggle", "Hold"], 
            initial_value=CONFIG.gyro_activation_mode, 
            command=self.update_act_setting, 
            bg_color=background_color
        )
        self.gyro_act_switch.grid(row=1, column=1, columnspan=2, padx=5, pady=(10, 0), sticky="w")
        
        tk.Label(self.gyro_frame, text="Stick Assist:", bg=background_color, font=("Arial", 12, "bold")).grid(row=1, column=3, padx=(20, 5), pady=(10, 0), sticky="e")
        self.stick_scale = tk.Scale(self.gyro_frame, from_=0, to=10, resolution=0.2, orient=tk.HORIZONTAL, length=120, bg=background_color, font=("Arial", 12, "bold"), command=self.on_gyro_setting_changed)
        self.stick_scale.set(getattr(CONFIG, "stick_mouse_sensitivity", 5.0))
        self.stick_scale.grid(row=1, column=4, columnspan=3, pady=(10, 0), sticky="w")
        
        self.calibrate_btn = tk.Button(self.gyro_frame, text="Calibrate Gyro", command=self.on_calibrate_clicked, bg="#e0e0e0", font=("Arial", 12, "bold"))
        self.calibrate_btn.grid(row=1, column=5, columnspan=2, padx=(20, 5), pady=(10, 0), sticky="ew")
        
    def update_mode_setting(self, val):
        CONFIG.gyro_mode = val
        self.on_gyro_setting_changed()
        
    def update_mouse_setting(self, val):
        CONFIG.mouse_config.enabled = val
        
        try:
            with open(CONFIG.config_file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            if 'mouse' not in data:
                data['mouse'] = {}
                
            data['mouse']['enabled'] = val
            
            with open(CONFIG.config_file_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False)
            logger.info(f"Mouse mode settings saved: {val}")
        except Exception as e:
            logger.error(f"Failed to save mouse settings: {e}")

    def update_act_setting(self, val):
        CONFIG.gyro_activation_mode = val
        self.on_gyro_setting_changed()
    
    def update_mouse_sensitivity(self, val):
        new_sens = float(val)
        CONFIG.mouse_config.sensitivity = new_sens
        
        try:
            with open(CONFIG.config_file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            if 'mouse' not in data:
                data['mouse'] = {}
            
            data['mouse']['sensitivity'] = new_sens
            
            with open(CONFIG.config_file_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False)
        except Exception as e:
            logger.error(f"Failed to save mouse sensitivity: {e}")

    def on_gyro_setting_changed(self, *args):
        CONFIG.gyro_sensitivity = float(self.sens_scale.get())
        CONFIG.stick_mouse_sensitivity = float(self.stick_scale.get())
        
        try:
            with open(CONFIG.config_file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            data['gyro_mode'] = CONFIG.gyro_mode
            data['gyro_sensitivity'] = CONFIG.gyro_sensitivity
            data['gyro_activation_mode'] = CONFIG.gyro_activation_mode
            data['stick_mouse_sensitivity'] = CONFIG.stick_mouse_sensitivity
            
            if 'gyro_smoothing' in data:
                del data['gyro_smoothing']
                
            with open(CONFIG.config_file_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False)
            logger.info("Gyro settings saved to yaml successfully.")
        except Exception as e:
            logger.error(f"Save Gyro settings failed: {e}")
            
    def on_calibrate_clicked(self):
        if not hasattr(self, 'current_controllers') or self.no_controllers:
            return

        for vc in self.current_controllers:
            if vc is not None:
                vc.start_calibration()

        self.calibrate_btn.config(state=tk.DISABLED, text="Calibrating (2..)")
        self.root.after(1000, lambda: self.calibrate_btn.config(text="Calibrating (1..)"))
        self.root.after(2000, lambda: self.calibrate_btn.config(state=tk.NORMAL, text="Calibration Done"))
    
    def init_settings_panel(self):
        self.settings_frame = tk.Frame(self.root, bg=background_color)
        self.settings_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        row_global = tk.Frame(self.settings_frame, bg=background_color)
        row_global.pack(side=tk.TOP, fill=tk.X, pady=5)
        
        tk.Label(row_global, text="Emu Mode:", bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(10, 2))
        self.sim_mode_switch = ToggleSwitch(row_global, ["Xbox", "PS4"], ["Xbox", "PS4"], getattr(CONFIG, "simulation_mode", "Xbox"), self.update_sim_mode_setting, background_color)
        self.sim_mode_switch.pack(side=tk.LEFT, padx=5)
        
        tk.Label(row_global, text="Layout:", bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(20, 2))
        self.layout_switch = ToggleSwitch(row_global, ["Xbox", "Switch"], ["Xbox", "Switch"], CONFIG.abxy_mode, self.update_layout_setting, background_color)
        self.layout_switch.pack(side=tk.LEFT, padx=5)

        tk.Label(row_global, text="Joy-con Mouse:", bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(20, 2))
        self.mouse_switch = ToggleSwitch(row_global, ["ON", "OFF"], [True, False], CONFIG.mouse_config.enabled, self.update_mouse_setting, background_color)
        self.mouse_switch.pack(side=tk.LEFT, padx=5)
        
        tk.Label(row_global, text="Sensitivity:", bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(10, 2))
        self.mouse_sens_scale = tk.Scale(row_global, from_=1, to=10, resolution=0.2, orient=tk.HORIZONTAL, length=120, bg=background_color, font=("Arial", 12, "bold"), command=self.update_mouse_sensitivity)
        self.mouse_sens_scale.set(CONFIG.mouse_config.sensitivity)
        self.mouse_sens_scale.pack(side=tk.LEFT)

        row_pro = tk.Frame(self.settings_frame, bg=background_color)
        row_pro.pack(side=tk.TOP, fill=tk.X, pady=5)
        
        tk.Label(row_pro, text="Pro Controller Buttons:", bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(10, 5))
        for key, label in [("gl", "GL:"), ("gr", "GR:"), ("c", "Chat (Joy-con/Pro):")]:
            tk.Label(row_pro, text=label, bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(5, 2))
            combo = ttk.Combobox(row_pro, values=BACK_BUTTON_OPTIONS, font=("Arial", 12, "bold"), state="readonly", width=10)
            combo.set(getattr(CONFIG, f"{key}_mapping"))
            combo.pack(side=tk.LEFT, padx=2)
            combo.bind("<<ComboboxSelected>>", self.on_setting_changed)
            setattr(self, f"{key}_combo", combo)

        row_jc = tk.Frame(self.settings_frame, bg=background_color)
        row_jc.pack(side=tk.TOP, fill=tk.X, pady=5)
        
        tk.Label(row_jc, text="Joy-con Rail Buttons:", bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(10, 5))
        
        left_rail_options = [opt for opt in BACK_BUTTON_OPTIONS if opt != "Gyro"]
        if getattr(CONFIG, "srl_mapping", "None") == "Gyro":
            CONFIG.srl_mapping = "None"

        tk.Label(row_jc, text="Left SR:", bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(5, 2))
        self.srl_combo = ttk.Combobox(row_jc, values=left_rail_options, font=("Arial", 12, "bold"), state="readonly", width=10)
        self.srl_combo.set(CONFIG.srl_mapping)
        self.srl_combo.pack(side=tk.LEFT, padx=2)
        self.srl_combo.bind("<<ComboboxSelected>>", self.on_setting_changed)

        tk.Label(row_jc, text="Right SL:", bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(15, 2))
        self.slr_combo = ttk.Combobox(row_jc, values=BACK_BUTTON_OPTIONS, font=("Arial", 12, "bold"), state="readonly", width=10)
        self.slr_combo.set(CONFIG.slr_mapping)
        self.slr_combo.pack(side=tk.LEFT, padx=2)
        self.slr_combo.bind("<<ComboboxSelected>>", self.on_setting_changed)
        
    
    def update_sim_mode_setting(self, val):
        CONFIG.simulation_mode = val
        try:
            with open(CONFIG.config_file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            data['simulation_mode'] = val
            
            with open(CONFIG.config_file_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False)
            
            if hasattr(self, 'current_controllers'):
                for vc in self.current_controllers:
                    if vc is not None:
                        vc.set_mode(val)
            
            logger.info(f"模擬模式已切換為: {val}，已即時套用。")
        except Exception as e:
            logger.error(f"儲存或切換模擬模式失敗: {e}")
    
    def update_layout_setting(self, val):
        CONFIG.abxy_mode = val
        self.on_setting_changed()

    def on_setting_changed(self, event=None):
        CONFIG.gl_mapping = self.gl_combo.get()
        CONFIG.gr_mapping = self.gr_combo.get()
        CONFIG.c_mapping = self.c_combo.get()
        CONFIG.slr_mapping = self.slr_combo.get()
        CONFIG.srl_mapping = self.srl_combo.get()
        
        try:
            with open(CONFIG.config_file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            data['abxy_mode'] = CONFIG.abxy_mode  
            data['gl_mapping'] = CONFIG.gl_mapping
            data['gr_mapping'] = CONFIG.gr_mapping
            data['c_mapping'] = CONFIG.c_mapping
            data['slr_mapping'] = CONFIG.slr_mapping
            data['srl_mapping'] = CONFIG.srl_mapping
            
            with open(CONFIG.config_file_path, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False)
            logger.info("Custom button settings saved successfully.")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    def update(self, controllers_info):
        self.current_controllers = controllers_info
        self.no_controllers = all(c is None for c in controllers_info)
        
        if self.main_frame is not None:
            self.main_frame.destroy()

        self.main_frame = tk.Frame(self.root, bg=background_color)
        self.main_frame.pack(pady=30, fill=tk.Y)

        if self.no_controllers:
            tk.Label(self.main_frame, text="Press button of a paired controller, or hold sync button to pair", font=self.font, bg=background_color).pack()
            pairing_hint = tk.Label(self.main_frame, image=self.pairing_hint_image, bg=background_color)
            pairing_hint.pack(pady=10)
        else:
            self.players_info = [PlayerInfoBlock(self.main_frame) for i in range(4)]

            for i, player_info in enumerate(self.players_info):
                controller_info = controllers_info[i]
                if controller_info is not None:
                    player_info.displayControllersInfo(controller_info)

    def start(self):
        self.is_quitting = False
        
        def update_controllers_callback_threadsafe(controllers: list[VirtualController]):
            if getattr(self, 'is_quitting', False): 
                return
                
            try:
                self.message_queue.put(controllers)
                self.root.event_generate(CONTROLLER_UPDATED_EVENT)
            except Exception:
                pass
        
        self.root.bind(CONTROLLER_UPDATED_EVENT, lambda e : self.update(self.message_queue.get()))
        
        t = threading.Thread(target=start_discoverer, args=(update_controllers_callback_threadsafe, self.quit_event))
        t.daemon = True
        t.start()

        def on_quit():
            if getattr(self, 'is_cleaning_up', False):
                return
            self.is_cleaning_up = True
            
            self.root.title("Switch2 Controllers - Disconnecting...")
            logger.info("執行關閉程序：正在通知所有控制器中斷藍牙連線...")

            def perform_cleanup():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    
                    tasks = []
                    if hasattr(self, 'current_controllers'):
                        for vc in self.current_controllers:
                            if vc is not None:
                                tasks.append(vc.disconnect())
                    
                    if tasks:
                        loop.run_until_complete(asyncio.gather(*tasks))
                        logger.info("所有實體連線已安全解除。")
                    
                    loop.close()
                except Exception as e:
                    logger.error(f"清理時發生錯誤: {e}")
                finally:
                    self.root.after(0, lambda: (self.root.destroy(), os._exit(0)))

            threading.Thread(target=perform_cleanup, daemon=True).start()

        self.root.protocol("WM_DELETE_WINDOW", on_quit)
        self.root.mainloop()

if __name__ == "__main__":
    window = ControllerWindow()
    window.init_interface()
    window.start()
