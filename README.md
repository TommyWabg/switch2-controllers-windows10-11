# switch2-controllers (Windows 10 & Pro Features Fork)

This fork is heavily optimized for Windows 10/11 users, featuring a fully interactive GUI, advanced Gyro mouse aiming, and on-the-fly layout switching. 

## Key Features

* **Windows 10 Native Compatibility:** Resolved the `AttributeError: property is not available...` crash. Runs flawlessly on Windows 10 (22H2 and above).
* **On-the-Fly Layout Switching:** No more multiple executables! Instantly toggle between **Nintendo Layout** (matching physical labels) and **Xbox Layout** (standard PC positioning) directly from the UI.
* **Racing Wheel Mode (Steering):** Reads the controller's absolute tilt (accelerometer) and maps it directly to the Left Analog Stick's X-axis.
* **High-Precision Gyro Mouse (FPS):** Play shooters with a high-polling rate, 1000Hz interpolation loop for ultra-smooth, jitter-free gyro aiming.
* **Stick Assist:** Allowing the right thumbstick to work alongside gyro aiming.
* **1-Click Gyro Calibration:** Built-in calibration tool to instantly calculate and permanently save sensor bias, eliminating gyro drift.
* **Custom Extra Button Remapping:** Fully remap extra buttons like `GL`, `GR`, and `C` to function as Gyro triggers or standard buttons.
* **Haptic & OS Integration:** Added rumble feedback (including a connection confirmation rumble) and mapped the Capture button to native Windows screenshots (`Win + PrtScn`).
* **Standalone Executable (.exe):** Fully packed with all dependencies (including vgamepad DLLs). No Python installation required.

## Quick Start

1. Download and install the [Nefarius ViGEmBus driver](https://github.com/nefarius/ViGEmBus/releases).
2. Download the `.exe` from the **[Releases]** page.
3. Launch the app **before** connecting your controller. 
4. Hold the Sync button on your controller, or press any button if it's already paired. **Do not** pair controllers manually in Windows Bluetooth settings; the app uses automatic GATT discovery.
5. Use the app's settings panel at the bottom to configure your preferred layout, gyro sensitivity, and custom mappings.

## Important Setting for Steam Users:
Because this app emulates an Xbox 360 controller, Steam Input might try to "help" by applying its own layout overrides, which can double-swap your buttons and mess up your in-game controls! 
**To ensure your layout stays consistent:**
1. Go to **Steam** > **Settings** > **Controller** > **Show Advanced Settings**.
2. Make sure "**Enable Steam Input for Xbox controllers**" is turned **ON**.
3. Now theSwitch_2_Controllers app will handle the layout switching for you!

## Gyro Calibration Guide

To ensure maximum precision and eliminate "cursor drift," follow these steps to calibrate your controller:
1.  **Stationary Placement:** Place your Pro Controller on a completely flat, stable surface. **Do not touch or move it during the process.**
2.  **Trigger Calibration:** Click the **[Calibrate Gyro]** button in the settings panel.
3.  **Wait for Countdown:** The UI will display a countdown (`Calibrating (2..)`). 
4.  **Completion:** Once the button displays `Calibration Done`, the software has calculated the hardware bias and saved it. You do not need to recalibrate unless you experience new drifting issues.

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
