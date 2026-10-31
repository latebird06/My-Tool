"""桌面划词翻译 —— 程序入口。

用法：
    pythonw main.py            正常启动（无控制台）
    python  main.py --debug    带控制台日志
    python  main.py --selftest 自检（配置/图标/文本处理/Win32/网络）
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import logging
import logging.handlers
import os
import sys
import tempfile
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

MUTEX_NAME = "Global\\MouseTranslate-SingleInstance-8f3c1a"

log = logging.getLogger("main")


# ---------------------------------------------------------------- 单实例
def acquire_single_instance():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return None
    return handle


def ping_existing_instance() -> bool:
    from app.win32api import WM_PING, WinService, user32

    hwnd = user32.FindWindowW(WinService.CLASS_NAME, None)
    if hwnd:
        user32.PostMessageW(hwnd, WM_PING, 0, 0)
        return True
    return False


# ---------------------------------------------------------------- 日志
def setup_logging(debug: bool) -> None:
    from app.config import ensure_dirs

    log_dir = ensure_dirs() / "logs"
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(
            log_dir / "app.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
    ]
    if debug or sys.stdout is not None and sys.stdout.isatty():
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def install_excepthook() -> None:
    def hook(exc_type, exc, tb):
        log.error("未捕获异常", exc_info=(exc_type, exc, tb))
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                f"{exc_type.__name__}: {exc}\n\n详细信息见日志：\n%APPDATA%\\MouseTranslate\\logs\\app.log",
                "划词翻译启动失败",
                0x10,
            )
        except Exception:
            pass

    sys.excepthook = hook


# ---------------------------------------------------------------- 自检
def selftest() -> int:
    """离线可跑的自检；网络部分只报告 INFO/WARN。"""
    sys.path.insert(0, str(APP_DIR))

    check = _Checker()
    from app import capture as cap
    from app.config import Config, config_dir
    from app.icons import ensure_icons
    from app.translate import PROVIDERS, chunk_paragraph, split_paragraphs

    # 1. 配置
    cfg = Config.load()
    cfg.set("popup_width", 700)
    cfg.save()
    check.equal(Config.load().get("popup_width"), 700, "配置读写")
    check.equal(cfg.path.exists(), True, "配置文件落盘")
    check.equal(str(config_dir()).startswith(os.environ["APPDATA"]), True, "配置隔离到临时目录")

    # 2. 图标
    icons = ensure_icons(APP_DIR / "assets")
    for key in ("on", "off", "app"):
        path = icons[key]
        check.true(path.exists() and path.stat().st_size > 500, f"图标 {path.name}")

    # 3. 文本处理
    raw = "This is a trans-\nlation test.\n\nSecond paragraph  here."
    cleaned = cap.clean_text(raw)
    check.equal("translation" in cleaned, True, "断词连字符合并")
    check.equal("\n\n" in cleaned, True, "保留段落空行")
    check.equal(cap.is_translatable("Hello, world! This is English.", cfg), True, "英文可翻译")
    check.equal(cap.is_translatable("这是一段中文，不应该翻译", cfg), False, "纯中文跳过")
    check.equal(cap.is_translatable("ab", cfg), False, "过短文本跳过")
    check.equal(len(chunk_paragraph("word " * 400, 450)) > 1, True, "超长段落分块")
    check.equal(len(split_paragraphs("a\n\nb\n\nc")), 3, "段落切分")

    # 4. tkinter
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        root.destroy()
        check.ok("tkinter 初始化")
    except Exception as exc:  # noqa: BLE001
        check.fail(f"tkinter 初始化: {exc}")

    # 5. Win32 剪贴板
    try:
        from app.win32api import Clipboard

        original = Clipboard.get_text()
        Clipboard.set_text("mouse-translate-selftest")
        check.equal(Clipboard.get_text(), "mouse-translate-selftest", "剪贴板读写")
        if original is not None:
            Clipboard.set_text(original)
    except Exception as exc:  # noqa: BLE001
        check.fail(f"剪贴板读写: {exc}")

    # 6. 翻译引擎连通性（信息性）
    try:
        from app.translate import Translator

        results = Translator(cfg).test("Hello")
        for item in results:
            label = f"引擎 {PROVIDERS[item['provider']].label}"
            if item["ok"]:
                check.ok(f"{label}: {item['detail']}")
            else:
                check.warn(f"{label}: {item['detail']}")
    except Exception as exc:  # noqa: BLE001
        check.warn(f"引擎测试异常: {exc}")

    return check.report()


class _Checker:
    def __init__(self):
        self.passed = 0
        self.warnings: list[str] = []
        self.failed: list[str] = []

    def ok(self, name: str):
        self.passed += 1
        print(f"[PASS] {name}")

    def true(self, condition, name: str):
        if condition:
            self.ok(name)
        else:
            self.fail(name + ": 条件不成立")

    def equal(self, actual, expected, name: str):
        if actual == expected:
            self.ok(name)
        else:
            self.fail(f"{name}: 期望 {expected!r}，实际 {actual!r}")

    def warn(self, msg: str):
        self.warnings.append(msg)
        print(f"[WARN] {msg}")

    def fail(self, msg: str):
        self.failed.append(msg)
        print(f"[FAIL] {msg}")

    def report(self) -> int:
        print()
        print(f"通过 {self.passed} 项，警告 {len(self.warnings)} 项，失败 {len(self.failed)} 项")
        if self.warnings:
            print("警告（通常是网络/代理导致，可在成品里点「测试翻译引擎」复查）：")
            for item in self.warnings:
                print("  -", item)
        return 1 if self.failed else 0


# ---------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="桌面划词翻译")
    parser.add_argument("--debug", action="store_true", help="输出调试日志到控制台")
    parser.add_argument("--selftest", action="store_true", help="运行自检后退出")
    parser.add_argument("--smoke", action="store_true", help="启动托盘做冒烟测试后自动退出")
    args = parser.parse_args(argv)

    if args.selftest or args.smoke:
        # 自检/冒烟完全隔离：配置/日志都写到项目内的临时目录，不碰用户真实配置
        sandbox_home = APP_DIR / (".selftest-appdata" if args.selftest else ".smoke-appdata")
        if sandbox_home.exists():
            import shutil

            shutil.rmtree(sandbox_home, ignore_errors=True)
        sandbox_home.mkdir(parents=True, exist_ok=True)
        os.environ["APPDATA"] = str(sandbox_home)

    from app import win32api

    win32api.set_dpi_aware()
    setup_logging(args.debug)

    if args.selftest:
        return selftest()

    install_excepthook()

    mutex = acquire_single_instance()
    if mutex is None:
        if ping_existing_instance():
            log.info("已有实例在运行，已通知其显示提示")
        else:
            log.info("已有实例在运行，但未找到窗口")
        return 0

    from app.app import App

    if args.smoke:
        app = App()
        app.root.after(1200, lambda: app._apply_mode(False, announce=False))
        app.root.after(2800, app.shutdown)
        app.run(auto_mode="on")
        log.info("冒烟测试完成")
        return 0

    app = App()
    try:
        app.run()
    finally:
        log.info("进程退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())



