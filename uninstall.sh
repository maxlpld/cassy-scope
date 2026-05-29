#!/usr/bin/env bash
set -euo pipefail
echo "[1/3] Removing app files..."
sudo rm -rf /opt/cassy
echo "[2/3] Removing desktop entry and CLI alias..."
sudo rm -f /usr/share/applications/cassy-scope.desktop /usr/local/bin/cassy-scope
echo "[3/3] (Optional) Removing icon cache entry..."
sudo rm -f /usr/share/icons/hicolor/256x256/apps/cassy-scope.png || true
sudo update-desktop-database >/dev/null 2>&1 || true
sudo gtk-update-icon-cache /usr/share/icons/hicolor >/dev/null 2>&1 || true
echo "Uninstall complete."
