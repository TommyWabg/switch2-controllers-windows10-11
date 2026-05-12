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
from discoverer import start_discoverer, set_shutting_down
from config import get_resource, CONFIG, BACK_BUTTON_OPTIONS
from virtual_controller import VirtualController
from discoverer import split_controller, merge_controllers, VIRTUAL_CONTROLLERS

logger = logging.getLogger(__name__)

controller_frame_size = 200
battery_height = 40

background_color = "#aaaaaa"
block_color = "#404040"
player_number_bg_color = "#8B8B8B"

CONTROLLER_UPDATED_EVENT = '<<ControllersUpdated>>'
pending_merge_vc_index = None

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
    def __init__(self, parent, window):
        self.parent = parent
        self.window = window
        self.controller_label = None
        self.player_led_label = None
        self.current_vc = None

        self.load_pictures()
        self.init_interface()

    def _on_split_clicked(self):
        if self.current_vc is not None:
            vc_index = self.current_vc.player_number - 1
            split_controller(vc_index)

    def _on_merge_clicked(self):
        global pending_merge_vc_index
        if self.current_vc is not None:
            vc_index = self.current_vc.player_number - 1
            if pending_merge_vc_index is None:
                pending_merge_vc_index = vc_index
            elif pending_merge_vc_index == vc_index:
                pending_merge_vc_index = None
            else:
                v1 = VIRTUAL_CONTROLLERS[pending_merge_vc_index]
                v2 = self.current_vc
                is_opposite = (v1.is_single_joycon_left() and v2.is_single_joycon_right()) or \
                              (v1.is_single_joycon_right() and v2.is_single_joycon_left())
                
                if is_opposite:
                    merge_controllers(pending_merge_vc_index, vc_index)
                    pending_merge_vc_index = None
                else:
                    # Switch selection if same-side Joycon clicked
                    pending_merge_vc_index = vc_index
            
            # Trigger UI refresh
            self.window.update(list(VIRTUAL_CONTROLLERS))

    def _on_vibrate_clicked(self):
        from controller import VibrationData
        if self.current_vc is not None and getattr(self.current_vc, 'loop', None):
            vib = VibrationData(lf_amp=800, hf_amp=800)
            off = VibrationData(lf_amp=0, hf_amp=0)
            for controller in self.current_vc.controllers:
                # First short vibrate (0.1s)
                asyncio.run_coroutine_threadsafe(controller.set_vibration(vib), self.current_vc.loop)
                self.parent.after(100, lambda c=controller, loop=self.current_vc.loop, o=off: 
                    asyncio.run_coroutine_threadsafe(c.set_vibration(o), loop))
                
                # Second short vibrate (starts at 0.2s, lasts 0.1s)
                self.parent.after(200, lambda c=controller, loop=self.current_vc.loop, v=vib: 
                    asyncio.run_coroutine_threadsafe(c.set_vibration(v), loop))
                self.parent.after(300, lambda c=controller, loop=self.current_vc.loop, o=off: 
                    asyncio.run_coroutine_threadsafe(c.set_vibration(o), loop))

    def _on_hold_mode_toggled(self, val):
        if self.current_vc is not None:
            self.current_vc.hold_mode = val
            # Update image
            self._update_controller_image()
            
    def _on_gyro_side_toggled(self, val):
        if self.current_vc is not None:
            self.current_vc.active_gyro_side = val
            self.window.update(list(VIRTUAL_CONTROLLERS))
            
    def _update_controller_image(self):
        if self.current_vc is None: return
        
        # Decide image
        if not self.current_vc.is_single():
            image = self.joycon2leftandright
        elif self.current_vc.is_single_joycon_right():
            image = self.joycon2right_sideway if self.current_vc.hold_mode == "Horizontal" else self.joycon2right_vertical
        elif self.current_vc.is_single_joycon_left():
            image = self.joycon2left_sideway if self.current_vc.hold_mode == "Horizontal" else self.joycon2left_vertical
        else:
            image = self.procontroller2
            
        if image:
            self.controller_label.configure(image=image)

    def init_interface(self):
        # Create outer container
        self.main_frame = tk.Frame(self.parent, width=controller_frame_size, height=controller_frame_size + 8 + 40, bg=player_number_bg_color)
        self.main_frame.pack_propagate(False)
        
        # Create persistent internal frames
        self.controllers_frame = tk.Frame(self.main_frame, width=controller_frame_size, height=controller_frame_size - battery_height, bg=block_color)
        self.controllers_frame.pack()
        self.controllers_frame.pack_propagate(False)

        self.battery_frame = tk.Frame(self.main_frame, width=controller_frame_size, height=battery_height, bg=block_color)
        self.battery_frame.pack()
        self.battery_frame.pack_propagate(False)

        self.player_row = None
        self.controller_label = None
        self.player_led_label = None

    def _on_close_clicked(self):
        if self.current_vc is not None:
            if hasattr(self, 'close_btn') and self.close_btn:
                self.close_btn.config(state=tk.DISABLED)
            self.current_vc.trigger_disconnect()

    def load_pictures(self):
        self.joycon2leftandright = tk.PhotoImage(file=get_resource("images/joycon2leftandright.png"))
        self.joycon2right_sideway = tk.PhotoImage(file=get_resource("images/joycon2right_sideway.png"))
        self.joycon2left_sideway = tk.PhotoImage(file=get_resource("images/joycon2left_sideway.png"))
        try:
            self.joycon2right_vertical = tk.PhotoImage(file=get_resource("images/joycon2right.png"))
            self.joycon2left_vertical = tk.PhotoImage(file=get_resource("images/joycon2left.png"))
        except Exception:
            self.joycon2right_vertical = self.joycon2right_sideway
            self.joycon2left_vertical = self.joycon2left_sideway
        self.procontroller2 = tk.PhotoImage(file=get_resource("images/procontroller2.png"))
        self.battery_h = tk.PhotoImage(file=get_resource("images/battery_h.png"))
        self.battery_m = tk.PhotoImage(file=get_resource("images/battery_m.png"))
        self.battery_l = tk.PhotoImage(file=get_resource("images/battery_l.png"))
        self.player_leds = {nb: tk.PhotoImage(file=get_resource(f"images/player{nb}.png")) for nb in range(1,5)}

    def clearControllerInfo(self):
        # Hide internal components instead of destroying for zero flicker
        for attr in ['controller_label', 'player_led_label', 'close_btn', 'split_btn', 'merge_btn', 'mode_switch', 'gyro_btn_l', 'gyro_btn_r', 'vibrate_btn', 'player_row', 'battery_label', 'battery_label2']:
            widget = getattr(self, attr, None)
            if widget is not None:
                # Use correct forget method based on original layout
                if attr in ['controller_label', 'player_row']:
                    widget.pack_forget()
                else:
                    widget.place_forget()

    def get_image_for_battery_level(self, controller: Controller):
        if controller.battery_voltage is None: return self.battery_l
        if controller.battery_voltage > 3.25: return self.battery_h
        if controller.battery_voltage > 3.125: return self.battery_m
        return self.battery_l

    def displayControllersInfo(self, virtualController : VirtualController):
        self.current_vc = virtualController
        
        # 1. Controller Image
        if not self.controller_label:
            self.controller_label = tk.Label(self.controllers_frame, bg=block_color)
        self.controller_label.pack(fill="none", expand=True)
        self._update_controller_image()

        # 2. Close Button
        if not getattr(self, 'close_btn', None):
            self.close_btn = tk.Button(self.controllers_frame, text="✖", bg=block_color, fg="#888888", bd=0, 
                                       font=("Arial", 14, "bold"), activebackground="#ff4444", activeforeground="white", 
                                       command=self._on_close_clicked)
        self.close_btn.place(x=controller_frame_size-30, y=5, width=25, height=25)
        
        if self.close_btn.cget("state") == tk.DISABLED:
            self.close_btn.config(state=tk.NORMAL)

        # 3. Battery Labels
        if virtualController.is_single():
            if not getattr(self, 'battery_label', None):
                self.battery_label = tk.Label(self.battery_frame, bg=block_color)
            self.battery_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            if virtualController.controllers:
                self.battery_label.config(image=self.get_image_for_battery_level(virtualController.controllers[0]))
            if getattr(self, 'battery_label2', None): self.battery_label2.place_forget()
        else:
            if not getattr(self, 'battery_label', None): self.battery_label = tk.Label(self.battery_frame, bg=block_color)
            if not getattr(self, 'battery_label2', None): self.battery_label2 = tk.Label(self.battery_frame, bg=block_color)
            self.battery_label.place(relx=0.4, rely=0.5, anchor=tk.CENTER)
            if len(virtualController.controllers) > 0:
                self.battery_label.config(image=self.get_image_for_battery_level(virtualController.controllers[0]))
            
            self.battery_label2.place(relx=0.6, rely=0.5, anchor=tk.CENTER)
            if len(virtualController.controllers) > 1:
                self.battery_label2.config(image=self.get_image_for_battery_level(virtualController.controllers[1]))
            
        # 4. Split / Merge / Gyro Buttons
        global pending_merge_vc_index
        if not virtualController.is_single():
            if not getattr(self, 'split_btn', None):
                self.split_btn = tk.Button(self.controllers_frame, text="Split", bg="#555555", fg="white", bd=1,
                                           font=("Arial", 10, "bold"), command=self._on_split_clicked)
            self.split_btn.place(x=5, y=5)
            
            if getattr(self, 'merge_btn', None): self.merge_btn.place_forget()
            if getattr(self, 'mode_switch', None): self.mode_switch.place_forget()

            if not getattr(self, 'gyro_btn_l', None):
                self.gyro_btn_l = tk.Button(self.battery_frame, text="L Gyro", font=("Arial", 8, "bold"), 
                                            command=lambda: self._on_gyro_side_toggled("Left"))
                self.gyro_btn_r = tk.Button(self.battery_frame, text="R Gyro", font=("Arial", 8, "bold"), 
                                            command=lambda: self._on_gyro_side_toggled("Right"))
            
            self.gyro_btn_l.place(relx=0.04, rely=0.5, anchor=tk.W)
            self.gyro_btn_r.place(relx=0.96, rely=0.5, anchor=tk.E)
            
            active_style = {"bg": "#D32F2F", "fg": "white", "activebackground": "#ff3333"}
            inactive_style = {"bg": "#555555", "fg": "white", "activebackground": "#666666"}
            self.gyro_btn_l.config(**(active_style if virtualController.active_gyro_side == "Left" else inactive_style))
            self.gyro_btn_r.config(**(active_style if virtualController.active_gyro_side == "Right" else inactive_style))
        else:
            if getattr(self, 'split_btn', None): self.split_btn.place_forget()
            if getattr(self, 'gyro_btn_l', None):
                self.gyro_btn_l.place_forget()
                self.gyro_btn_r.place_forget()

            vc_index = virtualController.player_number - 1
            is_left = virtualController.is_single_joycon_left()
            is_right = virtualController.is_single_joycon_right()
            is_this_joycon = is_left or is_right

            if is_this_joycon:
                has_opposite = any(vc for vc in VIRTUAL_CONTROLLERS if vc is not None and vc != self.current_vc and 
                                   ((is_left and vc.is_single_joycon_right()) or (is_right and vc.is_single_joycon_left())))
                
                if has_opposite or pending_merge_vc_index == vc_index:
                    if not getattr(self, 'merge_btn', None):
                        self.merge_btn = tk.Button(self.controllers_frame, fg="white", bd=1,
                                                   font=("Arial", 10, "bold"), command=self._on_merge_clicked)
                    self.merge_btn.place(x=5, y=5)
                    
                    merge_text = "Merge"; merge_bg = "#555555"
                    if pending_merge_vc_index == vc_index:
                        merge_text = "Selecting"; merge_bg = "#FF8C00"
                    elif pending_merge_vc_index is not None:
                        p_vc = VIRTUAL_CONTROLLERS[pending_merge_vc_index]
                        if p_vc and ((is_left and p_vc.is_single_joycon_right()) or (is_right and p_vc.is_single_joycon_left())):
                            merge_text = "Merge"; merge_bg = "#D32F2F"
                    
                    self.merge_btn.config(text=merge_text, bg=merge_bg)
                elif getattr(self, 'merge_btn', None):
                    self.merge_btn.place_forget()
                
                if not getattr(self, 'mode_switch', None):
                    self.mode_switch = ToggleSwitch(self.battery_frame, ["V", "H"], ["Vertical", "Horizontal"], virtualController.hold_mode, self._on_hold_mode_toggled, block_color)
                    self.mode_switch.btn_left.config(font=("Arial", 9, "bold"), width=2, padx=0, pady=0)
                    self.mode_switch.btn_right.config(font=("Arial", 9, "bold"), width=2, padx=0, pady=0)
                
                self.mode_switch.place(relx=0.95, rely=0.5, anchor=tk.E)
                self.mode_switch.set_value(virtualController.hold_mode)
            else:
                if getattr(self, 'merge_btn', None): self.merge_btn.place_forget()
                if getattr(self, 'mode_switch', None): self.mode_switch.place_forget()

        # 5. Player LED and Vibrate row
        if not getattr(self, 'player_row', None):
            self.player_row = tk.Frame(self.main_frame, bg=player_number_bg_color, width=controller_frame_size, height=40)
            self.player_row.pack_propagate(False)
            self.player_led_label = tk.Label(self.player_row, bg=player_number_bg_color)
            self.vibrate_btn = tk.Button(self.player_row, text="Vibrate", bg="#555555", fg="white", bd=1,
                                         font=("Arial", 9, "bold"), width=6, command=self._on_vibrate_clicked)
        
        self.player_row.pack(pady=10)
        self.player_led_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        self.vibrate_btn.place(relx=0.96, rely=0.5, anchor=tk.E)
        self.player_led_label.config(image=self.player_leds[virtualController.player_number])

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
        self.root.minsize(1000, 690)
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

        row_mouse = tk.Frame(self.settings_frame, bg=background_color)
        row_mouse.pack(side=tk.TOP, fill=tk.X, pady=5)

        tk.Label(row_mouse, text="Joy-con Mouse:", bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(10, 2))
        self.mouse_switch = ToggleSwitch(row_mouse, ["ON", "OFF"], [True, False], CONFIG.mouse_config.enabled, self.update_mouse_setting, background_color)
        self.mouse_switch.pack(side=tk.LEFT, padx=5)
        
        tk.Label(row_mouse, text="Sensitivity:", bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(10, 2))
        self.mouse_sens_scale = tk.Scale(row_mouse, from_=1, to=10, resolution=0.2, orient=tk.HORIZONTAL, length=120, bg=background_color, font=("Arial", 12, "bold"), command=self.update_mouse_sensitivity)
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
        
        tk.Label(row_jc, text="Left SR:", bg=background_color, font=("Arial", 12, "bold")).pack(side=tk.LEFT, padx=(5, 2))
        self.srl_combo = ttk.Combobox(row_jc, values=BACK_BUTTON_OPTIONS, font=("Arial", 12, "bold"), state="readonly", width=10)
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
            
            logger.info(f"Simulation mode switched to: {val}")
        except Exception as e:
            logger.error(f"Failed to save or switch simulation mode: {e}")
    
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
        # 1. Ensure main frame exists
        if self.main_frame is None:
            self.main_frame = tk.Frame(self.root, bg=background_color)
            self.main_frame.pack(pady=30, fill=tk.Y)
            self.players_info = None
            self.pairing_frame = None

        self.current_controllers = controllers_info
        any_connected = any(c is not None for c in controllers_info)
        self.no_controllers = not any_connected
        
        if any_connected:
            # Switch to 4-block mode
            if self.players_info is None:
                # Clear main_frame before switching mode
                for w in self.main_frame.winfo_children(): w.destroy()
                
                self.players_info = [PlayerInfoBlock(self.main_frame, self) for i in range(4)]
                for p in self.players_info:
                    p.main_frame.pack(padx=10, pady=10, side=tk.LEFT)
            
            # Update all 4 blocks (info blinks, but white boxes stay static)
            for i, player_info in enumerate(self.players_info):
                vc = controllers_info[i] if i < len(controllers_info) else None
                if vc is not None:
                    player_info.displayControllersInfo(vc)
                else:
                    player_info.clearControllerInfo()
        else:
            # No controllers connected, back to pairing hint
            if self.players_info is not None:
                for p in self.players_info:
                    p.main_frame.destroy()
                self.players_info = None
            
            # Recreate pairing hint UI
            if not any(isinstance(w, tk.Label) and w.cget("text").startswith("Press button") for w in self.main_frame.winfo_children()):
                # Clear stale components
                for w in self.main_frame.winfo_children(): w.destroy()
                
                tk.Label(self.main_frame, text="Press button of a paired controller, or hold sync button to pair", font=self.font, bg=background_color).pack()
                pairing_hint = tk.Label(self.main_frame, image=self.pairing_hint_image, bg=background_color)
                pairing_hint.pack(pady=10)

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
            set_shutting_down(True)
            
            # Hide window immediately
            self.root.withdraw()
            
            logger.info("Executing shutdown: Notifying controllers to disconnect...")

            def perform_cleanup():
                try:
                    vcs_to_disconnect = []
                    if hasattr(self, 'current_controllers'):
                        for vc in self.current_controllers:
                            if vc is not None and getattr(vc, 'loop', None) and vc.loop.is_running():
                                vcs_to_disconnect.append(vc)
                    
                    if vcs_to_disconnect:
                        loop = vcs_to_disconnect[0].loop
                        
                        async def disconnect_all():
                            all_controllers = []
                            for vc in vcs_to_disconnect:
                                # Unregister virtual controller notifications
                                if hasattr(vc, 'vg_controller') and vc.vg_controller:
                                    try: vc.vg_controller.unregister_notification()
                                    except: pass
                                all_controllers.extend(vc.controllers)
                            
                            # Interleaved disconnect to avoid Bluetooth driver overload
                            for c in all_controllers:
                                if c.client and c.client.is_connected:
                                    # Trigger disconnect background task
                                    asyncio.create_task(c.disconnect())
                                    # Sleep to give driver buffer time
                                    await asyncio.sleep(0.3)
                            
                            # Wait for background tasks to finish
                            await asyncio.sleep(3.5)

                        fut = asyncio.run_coroutine_threadsafe(disconnect_all(), loop)
                        try:
                            # 5.5s total timeout
                            fut.result(timeout=5.5)
                            logger.info("All physical connections attempted to release.")
                        except Exception:
                            pass
                            
                except Exception as e:
                    logger.error(f"Cleanup error: {e}")
                finally:
                    self.root.after(0, lambda: (self.root.destroy(), os._exit(0)))

            threading.Thread(target=perform_cleanup, daemon=True).start()
            
        self.root.protocol("WM_DELETE_WINDOW", on_quit)
        self.root.mainloop()

if __name__ == "__main__":
    window = ControllerWindow()
    window.init_interface()
    window.start()