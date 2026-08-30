#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$DATA_HOME/ip-purity"
APPLICATION_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"

for command_name in python3 ip ping resolvectl; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf '缺少系统工具：%s\n' "$command_name" >&2
        printf 'Ubuntu 可执行：sudo apt install python3 python3-gi gir1.2-gtk-3.0 iproute2 iputils-ping systemd-resolved\n' >&2
        exit 1
    fi
done

if ! python3 -c 'import gi; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' >/dev/null 2>&1; then
    printf '缺少 GTK 3 / PyGObject。Ubuntu 可执行：sudo apt install python3-gi gir1.2-gtk-3.0\n' >&2
    exit 1
fi

mkdir -p "$INSTALL_DIR/assets" "$APPLICATION_DIR" "$ICON_DIR"
install -m 755 "$SOURCE_DIR/check_ip_purity.py" "$INSTALL_DIR/check_ip_purity.py"
install -m 755 "$SOURCE_DIR/ipcheck_desktop_app.py" "$INSTALL_DIR/ipcheck_desktop_app.py"
install -m 644 "$SOURCE_DIR/README.md" "$INSTALL_DIR/README.md"
install -m 644 "$SOURCE_DIR/assets/ip-purity.svg" "$INSTALL_DIR/assets/ip-purity.svg"
install -m 644 "$SOURCE_DIR/assets/ip-purity.svg" "$ICON_DIR/local.ipcheck.purity.svg"
sed "s|@INSTALL_DIR@|$INSTALL_DIR|g" "$SOURCE_DIR/IP Purity.desktop" > "$APPLICATION_DIR/local.ipcheck.purity.desktop"
chmod 755 "$APPLICATION_DIR/local.ipcheck.purity.desktop"

command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPLICATION_DIR" >/dev/null 2>&1 || true

printf 'IP Purity 已安装。可从应用菜单搜索 “IP Purity” 启动。\n'

