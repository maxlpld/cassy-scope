#!/usr/bin/env bash
set -euo pipefail
# Make .NET find the LD DLLs
export MONO_PATH="/opt/cassy/lib"
# Matplotlib Tk GUI
export MPLBACKEND="TkAgg"
# Silence Mono WinForms/X11 input-method noise
export MONO_MWF_USE_XIM=0
export MONO_WINFORMS_XIM_STYLE=disabled
# Run the GUI with the app's venv (same interpreter used during install)
exec /opt/cassy/.venv/bin/python -u /opt/cassy/cassy_gui.py
