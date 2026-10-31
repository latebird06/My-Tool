"""选区抓取与文本清洗。

抓取路径：保存剪贴板文本 → SendInput 模拟 Ctrl+C → 等待剪贴板序号变化 →
读取文本 → 还原原剪贴板。全程约 100~400ms。

无法使用 Ctrl+C 的应用（部分终端、独占全屏）抓不到，属已知限制。
"""
from __future__ import annotations

import logging
import re
import time

from .win32api import Clipboard, send_ctrl_c

log = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_TOKEN_RE = re.compile(r"\S+")


def clean_text(raw: str) -> str:
    """合并断行、去掉连字符换行、压缩空白，尽量保留段落结构。"""
    if not raw:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # PDF / 网页复制常见：行尾连字符拆词
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = re.sub(r"\n{3,}", "\n\n", text)          # 多余空行压成一段
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)     # 段内换行变空格
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def analyze(text: str) -> tuple[int, int]:
    """返回 (拉丁字母数, 汉字数)。"""
    return len(_LATIN_RE.findall(text)), len(_CJK_RE.findall(text))


def is_translatable(text: str, cfg) -> bool:
    if not text:
        return False
    min_chars = int(cfg.get("min_chars", 4))
    if len(text) < min_chars:
        return False
    letters, cjk = analyze(text)
    if letters < 2:
        return False
    if cfg.get("skip_if_cjk", True) and cjk:
        ratio = letters / (letters + cjk)
        if ratio < 0.5:
            # 主要是中文的选区不翻译，避免中译中
            return False
    return True


def summarize(text: str, limit: int = 60) -> str:
    flat = " ".join(_TOKEN_RE.findall(text))
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


class SelectionCapture:
    """从当前前台窗口抓取选区文本。"""

    def __init__(self, cfg):
        self.cfg = cfg

    def capture(self) -> str | None:
        before = None
        if self.cfg.get("restore_clipboard", True):
            before = Clipboard.get_text()

        seq = Clipboard.sequence_number()
        send_ctrl_c()

        text: str | None = None
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            if Clipboard.sequence_number() != seq:
                # 给目标应用一点时间把数据写完
                time.sleep(0.03)
                text = Clipboard.get_text()
                break
            time.sleep(0.02)

        if text is None:
            log.debug("抓取超时：剪贴板未变化，可能没有选区")
        elif before is not None and self.cfg.get("restore_clipboard", True):
            # 还原用户原剪贴板文本（非文本内容无法还原，见 README）
            Clipboard.set_text(before)

        if text is None:
            return None
        cleaned = clean_text(text)
        return cleaned or None
