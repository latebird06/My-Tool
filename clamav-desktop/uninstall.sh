#!/usr/bin/env bash
set -euo pipefail

DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APPLICATION_DIR="$DATA_HOME/applications"
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
DESKTOP_DIR="${DESKTOP_DIR:-$HOME/Desktop}"

rm -f "$APPLICATION_DIR/local.clamav.ManualScan.desktop"
rm -f "$DATA_HOME/icons/hicolor/scalable/apps/local.clamav.ManualScan.svg"
rm -f "$DESKTOP_DIR/ClamAV.desktop"
rm -rf "$DATA_HOME/clamav-desktop"

command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database "$APPLICATION_DIR" >/dev/null 2>&1 || true

printf 'ClamAV 桌面界面已移除。系统 ClamAV 和扫描记录未删除。\n'
