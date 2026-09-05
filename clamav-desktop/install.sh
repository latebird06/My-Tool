#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$DATA_HOME/clamav-desktop"
APPLICATION_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
DESKTOP_DIR="${DESKTOP_DIR:-$HOME/Desktop}"

printf '安装 ClamAV、病毒库更新服务和 GTK 4 界面依赖……\n'
sudo apt update
sudo apt install -y clamav clamav-freshclam python3 python3-gi gir1.2-gtk-4.0 pkexec

mkdir -p "$INSTALL_DIR/assets" "$APPLICATION_DIR" "$ICON_DIR" "$DESKTOP_DIR"
install -m 755 "$SOURCE_DIR/clamav_scan_gui.py" "$INSTALL_DIR/clamav_scan_gui.py"
install -m 644 "$SOURCE_DIR/assets/clamav.svg" "$INSTALL_DIR/assets/clamav.svg"
install -m 644 "$SOURCE_DIR/assets/clamav.svg" "$ICON_DIR/local.clamav.ManualScan.svg"

sed "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
    "$SOURCE_DIR/ClamAV.desktop" > "$APPLICATION_DIR/local.clamav.ManualScan.desktop"
chmod 644 "$APPLICATION_DIR/local.clamav.ManualScan.desktop"
install -m 755 "$APPLICATION_DIR/local.clamav.ManualScan.desktop" "$DESKTOP_DIR/ClamAV.desktop"
gio set "$DESKTOP_DIR/ClamAV.desktop" metadata::trusted true 2>/dev/null || true

if grep -q '^Checks ' /etc/clamav/freshclam.conf; then
    sudo sed -i 's/^Checks .*/Checks 4/' /etc/clamav/freshclam.conf
fi
sudo sed -i 's/^# Check for new database [0-9][0-9]* times a day/# Check for new database 4 times a day/' \
    /etc/clamav/freshclam.conf
sudo systemctl enable --now clamav-freshclam.service
sudo systemctl restart clamav-freshclam.service

command -v gtk-update-icon-cache >/dev/null 2>&1 && \
    gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APPLICATION_DIR" >/dev/null 2>&1 || true

printf '安装完成。可从桌面或应用菜单启动 “ClamAV”。\n'
printf '病毒库每天检查更新 4 次；扫描不会自动删除文件。\n'
