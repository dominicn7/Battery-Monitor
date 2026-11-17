# Battery Monitor

A Windows tray app that shows the battery level of your Bluetooth peripherals (one icon per device) and alerts you when it gets critical, with an optional custom sound.

## Features
- One tray icon per connected device, with a device-specific glyph (headphones, mouse, keyboard, speaker, gamepad) and a battery level bar (green / orange / red). Hover for the exact percentage.
- Critical battery alert: Windows notification plus a sound. Choose the threshold (10–30%) and use your own `.wav` file.
- **Test critical alert** menu item to check that the notification and sound work.
- Interface language follows Windows (English, Portuguese, Spanish) and can be changed manually from the menu.
- Optional start with Windows. Runs as a single instance and uses almost no resources.

## Usage
1. Download `BatteryMonitor-v1.0.0.zip` from the [Releases](../../releases) page, extract it and run `BatteryMonitor.exe`. No installation or Python required.
2. Windows hides new tray icons. Click the `^` arrow next to the clock and drag the icons onto the taskbar once.
3. Right-click any icon for the menu: critical level, alert sound, test alert, language, start with Windows.

## Limitations
- Only devices that report their battery to Windows over Bluetooth are shown. 2.4 GHz USB dongles (many wireless mice and keyboards) are not supported.
- Paired but disconnected headphones are hidden. Battery levels are refreshed every 60 seconds.
- The `.exe` is not code-signed, so Windows SmartScreen may show an "unknown publisher" warning: click **More info → Run anyway**.

## Build from source
```
pip install pystray pillow pyinstaller
pyinstaller --noconsole --onefile --name BatteryMonitor --icon icon.ico battery_monitor.py
```
