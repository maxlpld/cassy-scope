# Ubuntu 26.04 compatibility patch

This is an installer/launcher-only change. The application GUI, acquisition code, fitting, plotting, data export, vendor DLLs, and udev rule are unchanged.

## Fixes

- Remove the unavailable GTK2 `libcanberra-gtk-module` package from installation. The GUI is Tkinter/TkAgg based and does not depend on GTK2.
- Upgrade from `pythonnet==3.0.5` (incompatible with Python 3.14) to `pythonnet==3.2.1` (supports Python 3.14).
- Repair existing installations: upgrade dependencies even if the existing virtual environment already exists, and back up the old environment if it was created for a different Python version.
- Choose the Mono runtime explicitly in the launcher and filter the outdated GTK2 canberra entry from an inherited `GTK_MODULES`.

## Installation (Ubuntu 26.04)

Download this branch as ZIP, extract it, then from the extracted project directory:

```bash
sudo ./setup_admin.sh
cassy-scope
```

Unplug and replug Sensor-CASSY 2 to apply updated udev rules.

## Quick checks

```bash
ls -l /dev/ldusb0 /dev/ttyACM* 2>/dev/null
ls -l /opt/cassy/lib/*.dll
/opt/cassy/.venv/bin/python /opt/cassy/test_scan_capture.py
```

Note: the GTK warning `Failed to load module canberra-gtk-module` alone is usually not fatal. Without an attached Sensor-CASSY 2, actual acquisition cannot be validated in the patching environment.
