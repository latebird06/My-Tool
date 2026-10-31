"""端到端 GUI 流程测试。

不走鼠标钩子，直接注入一段英文走完「翻译→浮窗→复制→点击外部关闭」，并校验
浮窗不会抢走前台焦点。

「真实鼠标点击」需要本进程能注入输入；在受限/沙箱环境里会被系统拦截，
此时自动降级为程序化调用并记为 SKIP（不影响结论）。

运行：python tools/test_popup_flow.py
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["APPDATA"] = str(ROOT / ".gui-test-appdata")

from app.app import App  # noqa: E402
from app.config import Config  # noqa: E402
from app.win32api import Clipboard, cursor_pos, foreground_hwnd, mouse_click  # noqa: E402

SAMPLE = (
    "The ultrasonic welding process creates a metallurgical bond between copper "
    "conductors without melting the bulk material. Joint quality depends mainly on "
    "welding force, vibration amplitude, and cycle time."
)

results: list[tuple[str, str, str]] = []  # (status, name, detail)
state: dict[str, object] = {}


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"[{status}] {name} {detail}")


def cursor_movable() -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = ctypes.c_bool
    x, y = cursor_pos()
    user32.SetCursorPos(x + 5, y + 5)
    moved = cursor_pos() != (x, y)
    user32.SetCursorPos(x, y)
    return moved


def main() -> int:
    cfg = Config.load()
    cfg.set("ask_mode_on_start", False)
    cfg.set("mode", "idle")
    cfg.set("providers", ["bing", "mymemory"])
    cfg.save()

    app = App()
    popup = app.popup
    can_click = cursor_movable()
    record("INFO", "输入注入可用", "是（将测试真实点击）" if can_click else "否（沙箱限制，点击测试降级为 SKIP）")

    def step_inject() -> None:
        Clipboard.set_text(SAMPLE)
        x, y = cursor_pos()
        state["fg_before"] = foreground_hwnd()
        app._start_job(x, y, text=SAMPLE, reason="clipboard")

    def step_inspect() -> None:
        state["fg_after"] = foreground_hwnd()
        if not popup.visible:
            record("FAIL", "浮窗已弹出")
            return
        record("PASS", "浮窗已弹出")
        rect = popup.rect()
        translated = popup._translated
        widget_text = popup._text_widget.get("1.0", "end").strip() if popup._text_widget else ""
        provider = popup._provider.cget("text") if popup._provider else ""
        record("PASS" if rect and rect[0] >= 0 and rect[1] >= 0 else "FAIL",
               "浮窗在工作区内", f"rect={rect}")
        ok_cn = bool(widget_text) and any("\u4e00" <= ch <= "\u9fff" for ch in widget_text)
        record("PASS" if ok_cn else "FAIL", "译文为中文", widget_text[:48])
        record("PASS" if provider else "FAIL", "显示引擎名", provider)
        record("PASS" if rect and rect[2] == int(cfg.get("popup_width")) else "FAIL",
               "浮窗宽度符合配置", f"w={rect[2] if rect else None}")
        record("PASS" if state["fg_before"] == state["fg_after"] else "FAIL",
               "浮窗没有抢走前台焦点", f"{state['fg_before']} -> {state['fg_after']}")
        record("PASS" if popup._preview.cget("text") else "FAIL", "原文预览已显示")
        state["expect"] = translated
        if can_click:
            btn = popup._copy_btn
            mouse_click(btn.winfo_rootx() + btn.winfo_width() // 2,
                        btn.winfo_rooty() + btn.winfo_height() // 2)
        else:
            popup._copy()  # 环境不允许注入时退化为直接调用
            record("SKIP", "真实点击复制按钮", "本环境禁止输入注入")

    def step_verify_copy() -> None:
        expected = state.get("expect")
        actual = Clipboard.get_text()
        ok = bool(expected) and actual == expected
        record("PASS" if ok else "FAIL", "复制译文到剪贴板", repr((actual or "")[:40]))

    def step_close() -> None:
        if not popup.visible:
            record("PASS", "点击外部后自动关闭", "(已关闭)")
            return
        rect = popup.rect()
        popup._pinned = False
        app._on_mousedown(rect[0] - 60, rect[1] - 60)
        record("PASS" if not popup.visible else "FAIL", "点击外部后自动关闭")

    def finish() -> None:
        app.shutdown()

    app.root.after(300, lambda: app._apply_mode(False, announce=False))
    app.root.after(600, step_inject)
    app.root.after(9000, step_inspect)
    app.root.after(9800, step_verify_copy)
    app.root.after(10300, step_close)
    app.root.after(11300, finish)
    app.run(auto_mode="idle")

    passed = sum(1 for s, _, _ in results if s == "PASS")
    skipped = sum(1 for s, _, _ in results if s == "SKIP")
    failed = [r for r in results if r[0] == "FAIL"]
    print()
    print(f"通过 {passed} 项，跳过 {skipped} 项，失败 {len(failed)} 项")
    return 1 if failed or passed == 0 else 0


if __name__ == "__main__":
    sys.exit(main())


