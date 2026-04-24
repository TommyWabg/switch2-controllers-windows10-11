## Fork Features (Windows 10 Support & Dual Layouts)

This fork of `switch2-controllers` is optimized for Windows 10 users and offers two different button mapping versions to suit your preference:

* **Windows 10 Compatibility Fix:** Resolved the `AttributeError: property is not available in this version of Windows` crash. This app now runs natively on Windows 10 (22H2 and above).
* **Two Layout Options:** * **Nintendo Layout Version:** Swaps A/B and X/Y. Pressing the physical "A" button on your Joy-Con (right position) triggers the "A" input on PC. Perfect for those who want the labels to match.
    * **Xbox/Standard Layout Version:** Keeps the standard PC positioning. Pressing the physical "A" button (right position) triggers the "B" input on PC (matching the standard Xbox controller layout).
* **Standalone Executable (.exe):** Fully packed with all dependencies (including `vgamepad` DLLs and `resources`). No Python installation required.

### Quick Start
1. Download and install [Nefarius ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases).
2. Download your preferred `.exe` from the **[Releases]** page.
3. Run the `.exe` and follow the instructions. *Do not pair controllers in Windows Bluetooth settings; the app will discover them automatically.*

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
