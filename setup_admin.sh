#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/cassy"
APP_DESKTOP="/usr/share/applications/cassy-scope.desktop"
BIN_LINK="/usr/local/bin/cassy-scope"

echo "[1/8] Installing OS dependencies..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y mono-complete python3-venv python3-pip python3-tk libcanberra-gtk-module libcanberra-gtk3-module

echo "[2/8] Copying app to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}/lib" "${INSTALL_DIR}/udev"
install -m 0755 run_scope.sh  "${INSTALL_DIR}/run_scope.sh"
install -m 0755 cassy_gui.py  "${INSTALL_DIR}/cassy_gui.py"
install -m 0755 scope2.py     "${INSTALL_DIR}/scope2.py"
# copy test and readme (not executable)
install -m 0644 test_scan_capture.py "${INSTALL_DIR}/test_scan_capture.py"

# Copy DLLs if included in the pack
if ls lib/*.dll >/dev/null 2>&1; then
  cp -f lib/*.dll "${INSTALL_DIR}/lib/" || true
fi
# Copy language resources if present (e.g., lib/fr/LD.Api.resources.dll)
if ls lib/*/LD.Api.resources.dll >/dev/null 2>&1; then
  for d in lib/*; do
    [ -d "$d" ] || continue
    [ -f "$d/LD.Api.resources.dll" ] || continue
    mkdir -p "${INSTALL_DIR}/$d"
    cp -f "$d/LD.Api.resources.dll" "${INSTALL_DIR}/$d/"
  done
fi

echo "[3/8] Installing udev rule (if provided)..."
if [ -f udev/48-ldusb.rules ]; then
  install -m 0644 udev/48-ldusb.rules /etc/udev/rules.d/48-ldusb.rules
  udevadm control --reload-rules || true
  udevadm trigger || true
fi

echo "[4/8] Creating Python venv and installing Python packages..."
if [ ! -d "${INSTALL_DIR}/.venv" ]; then
  python3 -m venv "${INSTALL_DIR}/.venv"
  "${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip
  "${INSTALL_DIR}/.venv/bin/pip" install pythonnet==3.0.5 numpy matplotlib scipy
fi

echo "[5/8] Installing custom icon (if present)..."
if [ -f "icons/cassy-logo.png" ]; then
  install -m 0644 "icons/cassy-logo.png" "${INSTALL_DIR}/cassy-logo.png"
  # Optional: also install into icon theme for nicer integration
  install -D -m 0644 "${INSTALL_DIR}/cassy-logo.png"     /usr/share/icons/hicolor/256x256/apps/cassy-scope.png || true
  gtk-update-icon-cache /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi

echo "[6/8] Creating desktop launcher..."
ICON_LINE="Icon=utilities-system-monitor"
if [ -f "${INSTALL_DIR}/cassy-logo.png" ]; then
  ICON_LINE="Icon=${INSTALL_DIR}/cassy-logo.png"
fi
cat > "${APP_DESKTOP}" <<EOF
[Desktop Entry]
Type=Application
Name=CASSY Scope
Comment=Run Sensor-CASSY 2 oscilloscope and save data
Exec=/opt/cassy/run_scope.sh
${ICON_LINE}
StartupWMClass=CASSY Scope
Terminal=false
Categories=Education;Science;
StartupNotify=true
EOF
update-desktop-database >/dev/null 2>&1 || true

echo "[7/8] Creating convenience CLI launcher..."
ln -sf "${INSTALL_DIR}/run_scope.sh" "${BIN_LINK}"

echo "[8/8] Permissions..."
chmod -R a+rX "${INSTALL_DIR}" || true

echo
echo "Install complete. Look in your app menu for 'CASSY Scope'."
echo "You can also run it from a terminal with: cassy-scope"
