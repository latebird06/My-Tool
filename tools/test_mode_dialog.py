"""启动选择对话框测试：构建 → 点「常驻」→ 校验配置。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["APPDATA"] = str(ROOT / ".dialog-test-appdata")

from app.app import App  # noqa: E402
from app.popup import ModeDialog  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def main() -> int:
    app = App()
    chosen: list[str] = []

    def on_choose(mode: str) -> None:
        chosen.append(mode)

    dialog = ModeDialog(app.root, app.cfg, on_choose)
    app.root.update_idletasks()
    check("对话框已创建", dialog.win.winfo_exists() == 1)
    check("对话框标题正确", dialog.win.title() == "划词翻译", dialog.win.title())
    check("记住选择默认勾选", bool(dialog.remember.get()))

    dialog._choose("on")
    app.root.update_idletasks()
    check("回调收到 on", chosen == ["on"], str(chosen))
    check("配置 mode=on", app.cfg.get("mode") == "on", str(app.cfg.get("mode")))
    check("记住选择后不再询问", app.cfg.get("ask_mode_on_start") is False)

    app.shutdown()
    failed = [r for r in results if not r[1]]
    print(f"\n通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
