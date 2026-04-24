from dataclasses import dataclass
import os
import yaml
import logging

logger = logging.getLogger(__name__)


SWITCH_BUTTONS = {
    "X":     0x00000001,
    "Y":     0x00000002,
    "A":     0x00000004,
    "B":     0x00000008,
    "SR_R":  0x00000010,
    "SL_R":  0x00000020,
    "R":     0x00000040,
    "ZR":    0x00000080,
    "MINUS": 0x00000100,
    "PLUS":  0x00000200,
    "R_STK": 0x00000400,
    "L_STK": 0x00000800,
    "HOME":  0x00001000,
    "CAPT":  0x00002000,
    "C":     0x00004000,
    # unused 0x00008000,
    "DOWN":  0x00010000,
    "UP":    0x00020000,
    "RIGHT": 0x00040000,
    "LEFT":  0x00080000,
    "SR_L":  0x00100000,
    "SL_L":  0x00200000,
    "L":     0x00400000,
    "ZL":    0x00800000,
    "GR":    0x01000000,
    "GL":    0x02000000,
}

XB_BUTTONS = {
    "UP": 0x0001,
    "DOWN": 0x0002,
    "LEFT": 0x0004,
    "RIGHT": 0x0008,
    "START": 0x0010,
    "BACK": 0x0020,
    "L_STK": 0x0040,
    "R_STK": 0x0080,
    "LB": 0x0100,
    "RB": 0x0200,
    "GUIDE": 0x0400,
    "B": 0x1000,
    "A": 0x2000,
    "Y": 0x4000,
    "X": 0x8000,
}

@dataclass
class ButtonConfig:
    buttons: dict[int, int]
    left_trigger: list[int]
    right_trigger: list[int]

    def __init__(self, buttons_dict: dict[str, str]):
        self.buttons = {}
        self.left_trigger = []
        self.right_trigger = []

        for k, v in buttons_dict.items():
            if k not in SWITCH_BUTTONS:
                raise Exception(f"Unknown switch button name in config: {k}")
            
            switch_button = SWITCH_BUTTONS[k]
            if v is not None:
                if v == "LT":
                    self.left_trigger.append(switch_button)
                elif v == "RT":
                    self.right_trigger.append(switch_button)
                else:
                    if v not in XB_BUTTONS:
                        raise Exception(f"Unknown XB button name in config: {v}")
                    xb_button = XB_BUTTONS[v]

                    self.buttons[switch_button] = xb_button

    def convert_buttons(self, switch_buttons: int):
        xb_buttons = 0x0000
        for switch_button, xb_button in self.buttons.items():
            if switch_buttons & switch_button:
                xb_buttons |= xb_button

        left_trigger = any([b & switch_buttons for b in self.left_trigger])
        right_trigger = any([b & switch_buttons for b in self.right_trigger])

        return xb_buttons, left_trigger, right_trigger

@dataclass
class MouseButtonConfig:
    left_button: int
    middle_button: int
    right_button: int

    def __init__(self, buttons_dict: dict[str, str]):
        self.left_button = SWITCH_BUTTONS[buttons_dict["left_button"]]
        self.middle_button = SWITCH_BUTTONS[buttons_dict["middle_button"]]
        self.right_button = SWITCH_BUTTONS[buttons_dict["right_button"]]

@dataclass
class MouseConfig:
    enabled: bool
    sensitivity: float
    scroll_sensitivity: float
    joycon_l_buttons: MouseButtonConfig
    joycon_r_buttons: MouseButtonConfig

    def __init__(self, config_dict: dict[str, str]):
        self.enabled = config_dict["enabled"]
        self.sensitivity = config_dict["sensitivity"]
        self.scroll_sensitivity = config_dict["scroll_sensitivity"]
        buttons_config = config_dict["buttons"]
        self.joycon_l_buttons = MouseButtonConfig(buttons_config["left_joycon"])
        self.joycon_r_buttons = MouseButtonConfig(buttons_config["right_joycon"])


@dataclass
class Config:
    combine_joycons: bool
    deadzone: int
    dual_joycons_config: ButtonConfig
    single_joycon_l_config: ButtonConfig
    single_joycon_r_config: ButtonConfig
    procon_config: ButtonConfig
    mouse_config: MouseConfig

    def __init__(self, config_file_path: str):

        with open(config_file_path) as cf:
            config = yaml.safe_load(cf)

            self.combine_joycons = config["combine_joycons"]
            self.deadzone = config["deadzone"]

            buttons_config = config["buttons"]

            self.dual_joycons_config = ButtonConfig(buttons_config["dual_joycons"])
            self.single_joycon_l_config = ButtonConfig(buttons_config["single_joycon_l"])
            self.single_joycon_r_config = ButtonConfig(buttons_config["single_joycon_r"])
            self.procon_config = ButtonConfig(buttons_config["procon"])

            self.mouse_config = MouseConfig(config["mouse"])

        logger.info(f"Config successfully read {self}")

def get_resource(resource_path: str):
    return os.path.join(os.path.dirname(__file__), 'resources', resource_path)
    
CONFIG = Config(get_resource("config.yaml"))
