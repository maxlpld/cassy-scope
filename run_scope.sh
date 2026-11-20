#!/usr/bin/env bash
set -euo pipefail
# Make .NET find the LD DLLs
export MONO_PATH="/opt/cassy/lib"
export PYTHONNET_RUNTIME="mono"
# Remove a stale reference to the obsolete GTK2 canberra module, without
# changing unrelated GTK settings inherited from the desktop session.
if [[ -n "${GTK_MODULES:-}" ]]; then
  _gtk_modules=()
  IFS=':' read -r -a _gtk_original <<< "$GTK_MODULES"
  for _module in "${_gtk_original[@]}"; do
    if [[ -n "$_module" && "$_module" != "canberra-gtk-module" ]]; then
      _gtk_modules+=("$_module")
    fi
  done
  GTK_MODULES="$(IFS=:; echo "${_gtk_modules[*]}")"
  export GTK_MODULES
fi
# Matplotlib Tk GUI
export MPLBACKEND="TkAgg"
# Silence Mono WinForms/X11 input-method noise
export MONO_MWF_USE_XIM=0
export MONO_WINFORMS_XIM_STYLE=disabled
# Run the GUI with the app's venv (same interpreter used during install)
exec /opt/cassy/.venv/bin/python -u /opt/cassy/cassy_gui.py
