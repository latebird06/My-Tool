"""生成托盘/程序图标（无第三方依赖）。

ICO 内含 16x16 与 32x32 两档 32bpp 位图，用 4x 超采样做抗锯齿。
图形：圆底 + 白色 "T"（Translate）；常驻=蓝色，挂机=灰色。
"""
from __future__ import annotations

import struct
from pathlib import Path

BLUE = (59, 130, 246)
GRAY = (110, 116, 128)
WHITE = (255, 255, 255)


def _inside_circle(x: float, y: float, size: int) -> bool:
    cx = cy = size / 2.0
    r = size * 0.445
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _inside_glyph(x: float, y: float, size: int) -> bool:
    """白色 "T"：横杠 + 竖杠。"""
    cx = cy = size / 2.0
    bar = abs(x - cx) <= size * 0.30 and abs(y - (cy - size * 0.22)) <= size * 0.045
    stem = abs(x - cx) <= size * 0.075 and abs(y - (cy + size * 0.02)) <= size * 0.24
    return bar or stem


def _render_rgba(size: int, base: tuple[int, int, int], ss: int = 4) -> list[tuple[int, int, int, int]]:
    """返回自上而下的 RGBA 像素列表（超采样后取平均）。"""
    pixels: list[tuple[int, int, int, int]] = []
    inv = 1.0 / (ss * ss)
    for py in range(size):
        for px in range(size):
            r = g = b = a = 0.0
            for sy in range(ss):
                for sx in range(ss):
                    x = px + (sx + 0.5) / ss
                    y = py + (sy + 0.5) / ss
                    if not _inside_circle(x, y, size):
                        continue
                    if _inside_glyph(x, y, size):
                        cr, cg, cb = WHITE
                    else:
                        cr, cg, cb = base
                    r += cr
                    g += cg
                    b += cb
                    a += 255.0
            if a <= 0:
                pixels.append((0, 0, 0, 0))
            else:
                n = a / 255.0
                pixels.append((
                    int(round(r / n)),
                    int(round(g / n)),
                    int(round(b / n)),
                    int(round(a * inv)),
                ))
    return pixels


def _dib(size: int, pixels: list[tuple[int, int, int, int]]) -> bytes:
    """32bpp 位图 + 1bpp AND 掩码，拼成 ICO 内嵌的 DIB。"""
    rows = []
    for y in range(size - 1, -1, -1):  # 位图自下而上
        row = bytearray()
        for x in range(size):
            r, g, b, a = pixels[y * size + x]
            row += bytes((b, g, r, a))
        rows.append(bytes(row))
    xor = b"".join(rows)

    stride = ((size + 31) // 32) * 4
    mask_rows = []
    for y in range(size - 1, -1, -1):
        bits = bytearray(stride)
        for x in range(size):
            _, _, _, a = pixels[y * size + x]
            if a < 128:  # 透明
                bits[x // 8] |= 0x80 >> (x % 8)
        mask_rows.append(bytes(bits))
    mask = b"".join(mask_rows)

    header = struct.pack(
        "<IiiHHIIiiII",
        40,          # biSize
        size,        # biWidth
        size * 2,    # biHeight（XOR + AND）
        1,           # biPlanes
        32,          # biBitCount
        0,           # biCompression
        0,           # biSizeImage
        0, 0, 0, 0,  # 分辨率/调色板
    )
    return header + xor + mask


def write_ico(path: Path, base: tuple[int, int, int], sizes=(16, 32)) -> Path:
    images = [(size, _dib(size, _render_rgba(size, base))) for size in sizes]
    out = bytearray(struct.pack("<HHH", 0, 1, len(images)))
    offset = 6 + 16 * len(images)
    entries = bytearray()
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0, 0, 1, 32,
            len(data),
            offset,
        )
        offset += len(data)
    out += entries
    for _, data in images:
        out += data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return path


def ensure_icons(assets_dir: Path) -> dict[str, Path]:
    """确保三个图标文件存在（缺失才生成，已存在则复用）。"""
    assets_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "on": assets_dir / "tray_on.ico",
        "off": assets_dir / "tray_off.ico",
        "app": assets_dir / "app.ico",
    }
    targets = {
        "on": BLUE,
        "off": GRAY,
        "app": BLUE,
    }
    for key, path in paths.items():
        if not path.exists() or path.stat().st_size < 200:
            write_ico(path, targets[key])
    return paths
