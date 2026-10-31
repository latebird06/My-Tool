"""预生成图标文件（安装脚本/首次运行都可调用）。

    python tools/make_icons.py [输出目录]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.icons import ensure_icons  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "assets"
    paths = ensure_icons(out)
    for key, path in paths.items():
        print(f"{key}: {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
