"""配置读写：%APPDATA%\\MouseTranslate\\config.json。

首次运行时自动生成默认配置；损坏时回退默认值并备份原文件。
"""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

APP_NAME = "MouseTranslate"

DEFAULTS = {
    # 启动状态：on = 常驻（监听划词），idle = 挂机（暂停监听）
    "mode": "on",
    "ask_mode_on_start": True,

    # 触发：auto = 松开鼠标即翻译；False = 只用托盘/热键
    "auto_translate": True,

    # 划词判定与过滤
    "min_chars": 4,
    "max_chars": 20000,
    "min_drag_px": 6,
    "cooldown_ms": 700,
    "skip_if_cjk": True,

    # 翻译引擎：按顺序尝试，第一个成功的生效
    "providers": ["bing", "mymemory", "google"],
    "source_lang": "auto",
    "target_lang": "zh-CN",
    "request_timeout_s": 9,

    # 抓取行为
    "restore_clipboard": True,

    # 界面
    "popup_width": 640,
    "popup_max_height": 560,
    "font_family": "Microsoft YaHei UI",
    "font_size_px": -15,
    "cache_size": 200,
    "log_level": "INFO",
}


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_NAME


class Config:
    """简单的字典式配置，带默认值合并与原子保存。"""

    def __init__(self, data: dict, path: Path):
        self._data = data
        self.path = path

    # ------------------------------------------------------------------ 读取
    @classmethod
    def load(cls) -> "Config":
        path = config_dir() / "config.json"
        data = dict(DEFAULTS)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data.update({k: v for k, v in raw.items() if k in DEFAULTS})
            except Exception:
                # 损坏：备份后使用默认值，避免程序起不来
                try:
                    path.replace(path.with_suffix(f".bad-{int(time.time())}.json"))
                except Exception:
                    pass
        cfg = cls(data, path)
        if not path.exists():
            cfg.save()
        return cfg

    # ------------------------------------------------------------------ 访问
    def get(self, key, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value):
        self._data[key] = value

    def update(self, mapping: dict):
        for key, value in mapping.items():
            if key in DEFAULTS:
                self._data[key] = value

    def as_dict(self) -> dict:
        return dict(self._data)

    # ------------------------------------------------------------------ 保存
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def open_in_editor(self):
        """用系统默认程序打开配置文件（Windows）。"""
        os.startfile(str(self.path))  # noqa: S606 - 仅本地配置


def ensure_dirs() -> Path:
    d = config_dir()
    (d / "logs").mkdir(parents=True, exist_ok=True)
    return d


def backup_config(path: Path) -> None:
    try:
        shutil.copy2(path, path.with_suffix(f".bak-{int(time.time())}.json"))
    except Exception:
        pass
