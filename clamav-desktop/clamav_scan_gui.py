#!/usr/bin/python3

import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk


APP_ID = "local.clamav.ManualScan"
CSS = r"""
window { background: #f5f1ea; color: #20252f; }
.shell { background: #fffdfa; padding: 30px 42px 34px; }
.brand { font-size: 20px; font-weight: 800; }
.brand-sub, .muted { color: #7d8694; font-size: 12px; }
.mark {
  background: #ff8c42; color: white; border-radius: 14px;
  font-size: 22px; font-weight: 900; min-width: 42px; min-height: 42px;
}
.status-card, .tip-card {
  background: white; border: 1px solid #e9e5dd; border-radius: 16px;
  padding: 13px 16px;
}
.status-value { font-weight: 700; font-size: 13px; }
.eyebrow { color: #ff8c42; font-size: 12px; font-weight: 800; }
.hero { font-size: 30px; font-weight: 900; letter-spacing: -1px; }
.intro { color: #7d8694; font-size: 14px; }
button.mode-card {
  background: white; color: #20252f; border: 1px solid #e9e5dd;
  border-radius: 18px; padding: 16px 18px; box-shadow: none;
}
button.mode-card:hover { border-color: #ff8c42; background: #fffaf6; }
button.mode-card.primary { border-color: #ff8c42; background: #fff7f1; }
.mode-icon { font-size: 23px; min-width: 35px; }
.mode-title { font-size: 16px; font-weight: 800; }
.mode-desc { color: #7d8694; font-size: 12px; }
.arrow { color: #ff8c42; font-size: 22px; }
.tip-card { background: #f8f6f1; color: #7d8694; font-size: 12px; border: 0; }
.scan-title { font-size: 26px; font-weight: 900; }
.scan-spinner { color: #ff8c42; min-width: 54px; min-height: 54px; }
progressbar trough { background: #eeeae2; border-radius: 99px; min-height: 8px; }
progressbar progress { background: #ff8c42; border-radius: 99px; min-height: 8px; }
button.orange {
  background: #ff8c42; color: white; border: 0; border-radius: 12px;
  padding: 10px 20px; font-weight: 800;
}
button.secondary {
  background: white; color: #7d8694; border: 1px solid #ddd7cd;
  border-radius: 12px; padding: 10px 20px;
}
.result-good { color: #38a169; }
.result-warn { color: #e95d5d; }
.summary {
  background: #f8f6f1; color: #596272; border-radius: 12px;
  padding: 14px; font-family: monospace; font-size: 12px;
}
"""


class ScannerWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="ClamAV 手动扫描")
        self.set_default_size(710, 650)
        self.set_size_request(620, 560)
        self.set_icon_name("security-high-symbolic")
        self.proc = None
        self.prepare_proc = None
        self.cancel_requested = False
        self.log_file = None
        self.total_files = 0
        self.completed_files = 0

        self.shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.shell.add_css_class("shell")
        self.set_child(self.shell)
        self.connect("close-request", self.on_close_request)
        self.show_home()

    def clear(self):
        child = self.shell.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.shell.remove(child)
            child = next_child

    @staticmethod
    def label(text, css=None, xalign=0.0, wrap=False):
        widget = Gtk.Label(label=text, xalign=xalign)
        widget.set_wrap(wrap)
        if css:
            widget.add_css_class(css)
        return widget

    def add_header(self):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        mark = self.label("C", "mark", 0.5)
        mark.set_valign(Gtk.Align.CENTER)
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        copy.append(self.label("ClamAV", "brand"))
        copy.append(self.label("本地文件安全扫描", "brand-sub"))
        row.append(mark)
        row.append(copy)
        self.shell.append(row)

    def database_status(self):
        candidates = [
            Path("/var/lib/clamav/daily.cvd"),
            Path("/var/lib/clamav/daily.cld"),
        ]
        existing = [path for path in candidates if path.exists()]
        if not existing:
            return "病毒库尚未就绪"
        stamp = datetime.fromtimestamp(max(p.stat().st_mtime for p in existing))
        return f"病毒库已更新 · {stamp:%Y-%m-%d %H:%M}"

    def show_home(self):
        self.clear()
        self.add_header()

        status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status.add_css_class("status-card")
        status.set_margin_top(25)
        status.append(self.label(self.database_status(), "status-value"))
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        status.append(spacer)
        status.append(self.label("每天检查更新 4 次", "muted"))
        self.shell.append(status)

        hero_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        hero_box.set_margin_top(28)
        hero_box.set_margin_bottom(18)
        hero_box.append(self.label("选择一次主动扫描", "eyebrow"))
        hero_box.append(self.label("检查可疑文件，\n保持工程干净。", "hero"))
        hero_box.append(self.label(
            "扫描只读取文件并报告结果，不会自动删除或隔离任何内容。",
            "intro", wrap=True,
        ))
        self.shell.append(hero_box)

        cards = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=11)
        cards.append(self.mode_card("⇩", "扫描下载目录", "检查最近下载的软件、压缩包与文档", "downloads", True))
        cards.append(self.mode_card("⌂", "扫描个人文件＋data盘", "覆盖个人资料、工程文件和 EDA 数据", "personal"))
        cards.append(self.mode_card("⌕", "自己选择文件夹", "只检查你指定的位置", "choose"))
        cards.append(self.mode_card("✦", "深度全盘扫描", "覆盖已挂载文件，跳过系统虚拟目录", "full"))
        self.shell.append(cards)

        tip = self.label(
            "提示　普通下载先用“扫描下载目录”；全盘扫描耗时较长，并需要系统密码。",
            "tip-card", wrap=True,
        )
        tip.set_margin_top(22)
        self.shell.append(tip)

    def mode_card(self, icon, title, desc, action, primary=False):
        button = Gtk.Button()
        button.add_css_class("mode-card")
        if primary:
            button.add_css_class("primary")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        row.append(self.label(icon, "mode-icon", 0.5))
        copy = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        copy.set_hexpand(True)
        copy.append(self.label(title, "mode-title"))
        copy.append(self.label(desc, "mode-desc", wrap=True))
        row.append(copy)
        row.append(self.label("→", "arrow", 1.0))
        button.set_child(row)
        button.connect("clicked", lambda _button: self.choose_action(action))
        return button

    def choose_action(self, action):
        if action == "downloads":
            result = subprocess.run(
                ["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, check=False
            )
            download_dir = result.stdout.strip() or str(Path.home() / "下载")
            self.start_scan([download_dir], "下载目录")
        elif action == "personal":
            targets = [str(Path.home())]
            if Path("/data").is_dir():
                targets.append("/data")
            self.start_scan(targets, "个人文件＋data盘")
        elif action == "choose":
            dialog = Gtk.FileChooserNative(
                title="选择要扫描的文件夹",
                transient_for=self,
                action=Gtk.FileChooserAction.SELECT_FOLDER,
                accept_label="开始扫描",
                cancel_label="取消",
            )
            dialog.connect("response", self.folder_chosen)
            dialog.show()
        elif action == "full":
            dialog = Gtk.MessageDialog(
                transient_for=self,
                modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK_CANCEL,
                text="确认深度全盘扫描？",
            )
            dialog.format_secondary_text(
                "扫描可能持续较长时间，并明显占用磁盘和处理器。继续后需要输入系统密码。"
            )
            dialog.connect("response", self.full_scan_confirmed)
            dialog.present()

    def folder_chosen(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            selected = dialog.get_file()
            if selected and selected.get_path():
                path = selected.get_path()
                dialog.destroy()
                self.start_scan([path], Path(path).name or path)
                return
        dialog.destroy()

    def full_scan_confirmed(self, dialog, response):
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.start_scan(["/"], "深度全盘扫描", privileged=True)

    def show_error(self, title, detail):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.CLOSE,
            text=title,
        )
        dialog.format_secondary_text(detail)
        dialog.connect("response", lambda current, _response: current.destroy())
        dialog.present()

    def start_scan(self, targets, label, privileged=False):
        missing = [target for target in targets if not Path(target).exists()]
        if missing:
            self.show_error("找不到扫描位置", "\n".join(missing))
            return

        state_dir = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        state_dir = state_dir / "clamav-manual-scan"
        state_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = state_dir / f"scan-{datetime.now():%Y%m%d-%H%M%S}.log"
        self.log_file.touch()
        self.cancel_requested = False
        self.total_files = 0
        self.completed_files = 0
        self.show_progress(label)
        threading.Thread(
            target=self.prepare_scan,
            args=(targets, privileged),
            daemon=True,
        ).start()

    def show_progress(self, label):
        self.clear()
        self.add_header()
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        content.set_valign(Gtk.Align.CENTER)
        content.set_vexpand(True)

        title = self.label("正在准备扫描", "scan-title", 0.5)
        content.append(title)
        self.progress_title = title
        content.append(self.label(label, "eyebrow", 0.5))
        content.append(self.label(
            "耗时取决于文件数量和压缩包大小，可以暂时做其他工作。",
            "intro", 0.5, True,
        ))

        progress = Gtk.ProgressBar()
        progress.set_show_text(True)
        progress.set_fraction(0.0)
        progress.set_text("正在统计文件…")
        progress.set_margin_top(12)
        content.append(progress)
        self.progress = progress

        cancel = Gtk.Button(label="停止扫描")
        cancel.add_css_class("secondary")
        cancel.set_halign(Gtk.Align.CENTER)
        cancel.set_margin_top(12)
        cancel.connect("clicked", self.cancel_scan)
        content.append(cancel)
        self.shell.append(content)

    def prepare_scan(self, targets, privileged):
        try:
            if privileged:
                total = self.count_full_scan_files()
            else:
                total = self.count_accessible_files(targets)
        except OSError as error:
            GLib.idle_add(self.preparation_failed, str(error))
            return

        if self.cancel_requested:
            GLib.idle_add(self.finish_scan, 130)
            return
        if total == 0:
            GLib.idle_add(self.preparation_failed, "所选位置没有可扫描的文件。")
            return

        self.total_files = total
        GLib.idle_add(self.begin_scan, targets, privileged)

    def count_accessible_files(self, targets):
        total = 0
        for target in targets:
            if self.cancel_requested:
                break
            path = Path(target)
            if path.is_file():
                total += 1
                continue
            for root, dirs, files in os.walk(path, followlinks=False):
                if self.cancel_requested:
                    break
                dirs[:] = [
                    name for name in dirs
                    if not Path(root, name).is_symlink()
                ]
                total += len(files)
        return total

    def count_full_scan_files(self):
        command = [
            "/usr/bin/pkexec", "/usr/bin/find", "/", "(",
            "-path", "/proc", "-o",
            "-path", "/sys", "-o",
            "-path", "/dev", "-o",
            "-path", "/run", "-o",
            "-path", "/snap", "-o",
            "-path", "/var/lib/clamav", ")",
            "-prune", "-o", "-type", "f", "-printf", ".",
        ]
        self.prepare_proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        total = 0
        while True:
            if self.cancel_requested:
                self.prepare_proc.terminate()
                break
            chunk = self.prepare_proc.stdout.read(65536)
            if not chunk:
                break
            total += len(chunk)
        result = self.prepare_proc.wait()
        self.prepare_proc = None
        if result != 0 and not self.cancel_requested:
            raise OSError("无法统计全盘文件，授权可能已取消。")
        return total

    def begin_scan(self, targets, privileged):
        command = ["/usr/bin/clamscan", "--recursive", "--verbose"]
        if privileged:
            command = [
                "/usr/bin/pkexec", "/usr/bin/clamscan", "--recursive", "--verbose",
                "--exclude-dir=^/proc($|/)",
                "--exclude-dir=^/sys($|/)",
                "--exclude-dir=^/dev($|/)",
                "--exclude-dir=^/run($|/)",
                "--exclude-dir=^/snap($|/)",
                "--exclude-dir=^/var/lib/clamav($|/)",
            ]
        command.extend(["--", *targets])
        try:
            self.proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                bufsize=1,
            )
        except OSError as error:
            self.preparation_failed(str(error))
            return False

        self.progress_title.set_text("正在检查文件")
        self.update_progress(0)
        threading.Thread(target=self.consume_scan_output, daemon=True).start()
        return False

    def consume_scan_output(self):
        update_step = max(1, min(100, self.total_files // 500 or 1))
        with self.log_file.open("w", encoding="utf-8", errors="replace") as log:
            for line in self.proc.stdout:
                is_file_result = line.startswith("/") and ": " in line
                if is_file_result:
                    self.completed_files += 1
                    if self.completed_files % update_step == 0:
                        GLib.idle_add(self.update_progress, self.completed_files)
                if not is_file_result or not line.rstrip().endswith(": OK"):
                    log.write(line)
            result = self.proc.wait()
        GLib.idle_add(self.finish_scan, result)

    def update_progress(self, completed):
        if not self.total_files:
            return False
        fraction = min(completed / self.total_files, 0.99)
        percent = int(fraction * 100)
        self.progress.set_fraction(fraction)
        self.progress.set_text(
            f"{percent}%　{min(completed, self.total_files):,} / {self.total_files:,} 个文件"
        )
        return False

    def preparation_failed(self, detail):
        self.show_home()
        self.show_error("无法准备扫描", detail)
        return False

    def finish_scan(self, result):
        if not self.cancel_requested and self.total_files:
            self.progress.set_fraction(1.0)
            self.progress.set_text(f"100%　{self.total_files:,} 个文件")
        self.proc = None
        self.prepare_proc = None
        self.show_result(result)
        return False

    def cancel_scan(self, _button=None):
        self.cancel_requested = True
        if self.prepare_proc and self.prepare_proc.poll() is None:
            self.prepare_proc.terminate()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def show_result(self, result):
        self.clear()
        self.add_header()

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=13)
        content.set_valign(Gtk.Align.CENTER)
        content.set_vexpand(True)

        if self.cancel_requested:
            symbol, heading, css, message = "■", "扫描已停止", "muted", "已保留本次扫描记录。"
        elif result == 0:
            symbol, heading, css, message = "✓", "未发现威胁", "result-good", "所选范围扫描完成。"
        elif result == 1:
            symbol, heading, css, message = "!", "发现可疑文件", "result-warn", "文件没有被自动删除，请查看记录。"
        else:
            symbol, heading, css, message = "!", "扫描未完整完成", "result-warn", "部分文件可能因权限或读取错误未被检查。"

        icon = self.label(symbol, css, 0.5)
        icon.add_css_class("hero")
        content.append(icon)
        content.append(self.label(heading, "scan-title", 0.5))
        content.append(self.label(message, "intro", 0.5, True))

        summary_text = self.read_summary()
        summary = self.label(summary_text, "summary", wrap=True)
        summary.set_selectable(True)
        summary.set_margin_top(10)
        content.append(summary)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        actions.set_halign(Gtk.Align.CENTER)
        again = Gtk.Button(label="再扫描一次")
        again.add_css_class("orange")
        again.connect("clicked", lambda _button: self.show_home())
        actions.append(again)
        details = Gtk.Button(label="查看完整记录")
        details.add_css_class("secondary")
        details.connect("clicked", self.show_log)
        actions.append(details)
        content.append(actions)
        self.shell.append(content)

    def read_summary(self):
        try:
            lines = self.log_file.read_text(errors="replace").splitlines()
        except OSError as error:
            return f"无法读取扫描记录：{error}"
        wanted = []
        keys = ("Scanned directories:", "Scanned files:", "Infected files:", "Total errors:", "Time:")
        for line in lines:
            if line.startswith(keys):
                wanted.append(line)
        return "\n".join(wanted) if wanted else f"扫描记录：{self.log_file}"

    def show_log(self, _button):
        if not self.log_file:
            return
        try:
            subprocess.Popen(["/usr/bin/xdg-open", str(self.log_file)])
        except OSError as error:
            self.show_error("无法打开扫描记录", str(error))

    def on_close_request(self, _window):
        if ((self.proc and self.proc.poll() is None) or
                (self.prepare_proc and self.prepare_proc.poll() is None)):
            self.cancel_scan()
        return False


class ScannerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def do_activate(self):
        window = self.props.active_window
        if not window:
            window = ScannerWindow(self)
        window.present()


if __name__ == "__main__":
    raise SystemExit(ScannerApp().run())
