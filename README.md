## 🌟 Fork Features (Windows 10 Fix & Nintendo Layout)

This is a modified fork of the original `switch2-controllers`. It includes the following quality-of-life improvements:

* **Windows 10 Compatibility Fix:** Fixed the `AttributeError: property is not available in this version of Windows` crash. The app now runs smoothly on Windows 10 (e.g., 22H2) by safely handling BLE connection parameters that are normally exclusive to Windows 11.
* **True Nintendo Button Layout:** Swapped the A/B and X/Y button mappings in the virtual controller configuration. It now matches the physical Nintendo Switch layout perfectly, rather than defaulting to the Xbox layout.
* **Standalone Executable (.exe) Available:** Packed with PyInstaller (including all hidden dependencies like `vgamepad` and `resources`). You can download the ready-to-use `.exe` directly from the **[Releases]** page—no Python or `pip install` required!

### 🚀 How to use the compiled version
1. Download the executable file from the **Releases** section.
2. Ensure you have the [Nefarius ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases) installed on your PC.
3. Simply double-click the `.exe` to run. *(Note: Do not pair the controllers in the Windows Bluetooth settings; let the app handle the connection.)*

---
*(Below is the original project description)*

# switch2 controllers
An app to use switch 2 joycons on pc as gamepad and mouse

### Usage

No need to pair the controller in the bluetooth settings.

Simply launch the app, and do what it says.

If you already paired the joycons in windows bluetooth settings, remove it before attempting to use it with this app.

### Using as a mouse

By default the app switches a joycon to mouse mode when it detects it's being used a mouse (side of of the joycon against a flat surface)

When in mouse mode, the following buttons are used as mouse buttons and no longer useable as gamepad buttons :
L/R : left click
ZL/ZR : right click
joystick : mouse wheel and middle button (click)

If you do not wish to use mouse mode, you can disable it in the config

### Using joycons sideways

By default, the app will always try to combine a right and left joycons together to make a single virtual controller.

If you wish to use both joycons sideway, you can hold SL\SR while turning them on
An other option is to set `combine_joycons` in the config to false so that the app will never try to combine joycons
