"""应用控制器：状态机、事件分发、翻译任务调度。"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

from . import capture as capture_mod
from .config import Config, config_dir, ensure_dirs
from .popup import ModeDialog, Popup
from .translate import PROVIDERS, TranslationError, Translator
from .win32api import (
    MENU_EXIT,
    MENU_IDLE,
    MENU_OPEN_CONFIG_DIR,
    MENU_RELOAD_CONFIG,
    MENU_RESIDENT,
    MENU_TEST_ENGINE,
    MENU_TRANSLATE_CLIPBOARD,
    Clipboard,
    WinService,
    cursor_pos,
    is_own_foreground,
)

log = logging.getLogger(__name__)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.report_callback_exception = self._on_tk_exception

        self.cfg = Config.load()
        ensure_dirs()
        self.events: queue.Queue = queue.Queue()
        self.translator = Translator(self.cfg)
        self.capture = capture_mod.SelectionCapture(self.cfg)
        self.popup = Popup(self.root, self.cfg, self.events)

        # 图标在安装到目标目录后就存在；缺失时当场生成
        from .icons import ensure_icons
        assets = Path(__file__).resolve().parent.parent / "assets"
        self.icons = ensure_icons(assets)

        self.win = WinService(self.events, self.icons, int(self.cfg.get("min_drag_px", 6)))
        self.resident = False
        self._last_trigger = 0.0
        self._last_text = ""
        self._last_text_ts = 0.0
        self._active_job = 0
        self._job_seq = 0
        self._quitting = False

    # ------------------------------------------------------------ 生命周期
    def run(self, auto_mode: str | None = None) -> None:
        """auto_mode: "on"/"idle" 时跳过启动对话框（冒烟测试用）。"""
        if not self.win.start():
            messagebox.showerror("启动失败", "Win32 服务线程未能启动，详见日志文件。")
            self.root.destroy()
            return
        self.root.after(40, self._pump)
        if auto_mode is not None:
            self._apply_mode(auto_mode == "on", announce=False)
        elif self.cfg.get("ask_mode_on_start", True):
            ModeDialog(self.root, self.cfg, self._on_mode_chosen)
        else:
            self._apply_mode(self.cfg.get("mode", "on") == "on", announce=False)
        self.root.mainloop()

    def _on_mode_chosen(self, mode: str) -> None:
        # 对话框出现在启动时，主循环尚未开始，直接用 after 挂到事件循环
        self.root.after(10, lambda: self._apply_mode(mode == "on", announce=True))

    def shutdown(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        log.info("退出应用")
        try:
            self.popup.hide()
            self.win.shutdown()
            self.win.wait()
        finally:
            try:
                self.root.destroy()
            except tk.TclError:
                pass

    def _on_tk_exception(self, exc, val, tb) -> None:
        log.error("Tk 回调异常: %s", val, exc_info=(exc, val, tb))
        self.win.post_notify("划词翻译出错", str(val)[:200])

    # ------------------------------------------------------------ 状态
    def _apply_mode(self, resident: bool, announce: bool = True) -> None:
        self.resident = resident
        self.cfg.set("mode", "on" if resident else "idle")
        self.cfg.save()
        self.win.post_set_mode(resident)
        if not resident:
            self.popup.hide()
        if announce:
            self.win.post_notify(
                "划词翻译",
                "已切换到常驻：选中英文即自动翻译" if resident else "已挂机：暂停监听划词",
            )

    # ------------------------------------------------------------ 事件泵
    def _pump(self) -> None:
        try:
            while True:
                self._handle(self.events.get_nowait())
        except queue.Empty:
            pass
        except Exception:
            log.exception("事件处理异常")
        if not self._quitting:
            self.root.after(40, self._pump)

    def _handle(self, event: tuple) -> None:
        kind = event[0]
        if kind == "mousedown":
            self._on_mousedown(event[1], event[2])
        elif kind == "drag":
            self._on_drag(event[1], event[2])
        elif kind == "hotkey":
            self._translate_clipboard()
        elif kind == "tray_click":
            self._apply_mode(not self.resident)
        elif kind == "menu":
            self._on_menu(event[1])
        elif kind == "second_instance":
            self.win.post_notify("划词翻译", "程序已在运行中，可从托盘图标操作")
        elif kind == "hook_failed":
            self.win.post_notify("划词翻译", "全局鼠标钩子安装失败，常驻模式不可用")
        elif kind == "hotkey_failed":
            self.win.post_notify("划词翻译", "热键 Ctrl+Alt+T 注册失败（可能被其他程序占用）")
        elif kind == "service_error":
            self.win.post_notify("划词翻译", event[1] if len(event) > 1 else "服务线程异常")
        elif kind == "worker_loading":
            self._on_worker_loading(*event[1:])
        elif kind == "worker_progress":
            self._on_worker_progress(*event[1:])
        elif kind == "worker_result":
            self._on_worker_result(*event[1:])
        elif kind == "worker_error":
            self._on_worker_error(*event[1:])
        elif kind == "retry":
            self._start_job(event[1], event[2], text=event[3], reason="retry")
        elif kind == "engine_test":
            self._show_engine_test(event[1])

    # ------------------------------------------------------------ 交互
    def _on_mousedown(self, x: int, y: int) -> None:
        if self.popup.visible and not self.popup.pinned and not self.popup.contains(x, y):
            self.popup.hide()

    def _on_drag(self, x: int, y: int) -> None:
        if not self.resident or not self.cfg.get("auto_translate", True):
            return
        if self.popup.visible and self.popup.contains(x, y):
            return
        if is_own_foreground():
            return
        now = time.monotonic()
        if (now - self._last_trigger) * 1000 < float(self.cfg.get("cooldown_ms", 700)):
            return
        self._last_trigger = now
        self._start_job(x, y, reason="drag")

    def _on_menu(self, menu_id: int) -> None:
        if menu_id == MENU_RESIDENT:
            self._apply_mode(True)
        elif menu_id == MENU_IDLE:
            self._apply_mode(False)
        elif menu_id == MENU_TRANSLATE_CLIPBOARD:
            self._translate_clipboard()
        elif menu_id == MENU_TEST_ENGINE:
            self._test_engines()
        elif menu_id == MENU_RELOAD_CONFIG:
            self._reload_config()
        elif menu_id == MENU_OPEN_CONFIG_DIR:
            try:
                os.startfile(str(config_dir()))
            except Exception as exc:
                log.warning("打开配置目录失败: %s", exc)
        elif menu_id == MENU_EXIT:
            self.shutdown()

    def _translate_clipboard(self) -> None:
        text = Clipboard.get_text()
        if not text or not text.strip():
            self.win.post_notify("划词翻译", "剪贴板里没有可翻译的文字")
            return
        x, y = cursor_pos()
        self._start_job(x, y, text=capture_mod.clean_text(text), reason="clipboard")

    def _reload_config(self) -> None:
        new_cfg = Config.load()
        self.cfg = new_cfg
        self.translator = Translator(new_cfg)
        self.capture = capture_mod.SelectionCapture(new_cfg)
        self.popup.cfg = new_cfg
        self.win.min_drag2 = int(new_cfg.get("min_drag_px", 6)) ** 2
        self._apply_mode(new_cfg.get("mode", "on") == "on", announce=False)
        self.win.post_notify("划词翻译", "配置已重新载入")

    # ------------------------------------------------------------ 翻译任务
    def _start_job(self, x: int, y: int, text: str | None = None, reason: str = "drag") -> None:
        self._job_seq += 1
        job = self._job_seq
        self._active_job = job
        cfg = self.cfg

        def worker() -> None:
            try:
                source_text = text
                if source_text is None:
                    source_text = self.capture.capture()
                    if not source_text:
                        return  # 没抓到选区：静默忽略
                    if not capture_mod.is_translatable(source_text, cfg):
                        log.debug("选区不满足翻译条件: %s", capture_mod.summarize(source_text))
                        return
                if reason != "retry" and self._is_duplicate(source_text):
                    log.debug("3 秒内重复选区，忽略")
                    return
                self._last_text, self._last_text_ts = source_text, time.monotonic()
                max_chars = int(cfg.get("max_chars", 20000))
                truncated = len(source_text) > max_chars
                if truncated:
                    source_text = source_text[:max_chars]
                preview = capture_mod.summarize(source_text)
                self.events.put(("worker_loading", job, x, y, preview))

                def progress(done: int, total: int) -> None:
                    if job == self._active_job:
                        self.events.put(("worker_progress", job, done, total))

                translated, provider = self.translator.translate(source_text, progress)
                if truncated:
                    translated += "\n\n（原文过长，已截断到 %d 字符）" % max_chars
                if job == self._active_job:
                    self.events.put(("worker_result", job, translated, provider, source_text))
            except TranslationError as exc:
                if job == self._active_job:
                    self.events.put(("worker_error", job, str(exc)))
            except Exception as exc:  # noqa: BLE001
                log.exception("翻译任务异常")
                if job == self._active_job:
                    self.events.put(("worker_error", job, f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=worker, name=f"translate-{job}", daemon=True).start()

    def _is_duplicate(self, text: str) -> bool:
        return text == self._last_text and (time.monotonic() - self._last_text_ts) < 3.0

    def _on_worker_loading(self, job: int, x: int, y: int, preview: str) -> None:
        if job != self._active_job:
            return
        self.popup.show_loading(x, y, preview)

    def _on_worker_progress(self, job: int, done: int, total: int) -> None:
        if job != self._active_job:
            return
        self.popup.show_progress(done, total)

    def _on_worker_result(self, job: int, translated: str, provider: str, source: str) -> None:
        # 用户已手动关掉浮窗时，不要把译文再弹回来
        if job != self._active_job or not self.popup.visible:
            return
        self.popup.show_result(translated, provider, source)

    def _on_worker_error(self, job: int, message: str) -> None:
        if job != self._active_job or not self.popup.visible:
            return
        log.warning("翻译失败: %s", message)
        self.popup.show_error(message)

    # ------------------------------------------------------------ 引擎诊断
    def _test_engines(self) -> None:
        self.win.post_notify("划词翻译", "正在测试翻译引擎…")

        def worker() -> None:
            try:
                results = self.translator.test()
            except Exception as exc:  # noqa: BLE001
                results = [{"provider": "?", "label": "测试异常", "ok": False,
                            "detail": str(exc), "ms": 0}]
            self.events.put(("engine_test", results))

        threading.Thread(target=worker, name="engine-test", daemon=True).start()

    def _show_engine_test(self, results: list[dict]) -> None:
        lines = []
        for item in results:
            mark = "✓" if item["ok"] else "✗"
            lines.append(f"{mark} {item['label']}  ({item['ms']} ms)")
            lines.append(f"    {item['detail']}")
        best = next((item["label"] for item in results if item["ok"]), None)
        lines.append("")
        lines.append(f"当前可用：{best}" if best else "当前没有可用引擎，请检查网络或代理设置。")
        messagebox.showinfo("翻译引擎测试", "\n".join(lines), parent=self.root)
