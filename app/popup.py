"""tkinter 界面：翻译浮窗 + 启动状态选择对话框。

设计要点：
- 浮窗不抢焦点（不调用 focus_force），划词时不会打断原应用输入；
- 浮窗出现在鼠标释放点附近，越界自动翻转/收进显示器工作区；
- 点击浮窗外部由全局钩子通知关闭（除非点了「固定」）。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

BORDER = "#3a4150"
BG = "#181b21"
PANEL = "#20242c"
TEXT = "#e7e9ee"
MUTED = "#8b93a3"
ACCENT = "#4f8cff"
ACCENT_HOVER = "#6b9dff"
WARN = "#ff7b72"
OK = "#3fb950"


class Popup:
    # 由 app 注入：调用后重新翻译
    def __init__(self, root: tk.Tk, cfg, events):
        self.root = root
        self.cfg = cfg
        self.events = events
        self.top: tk.Toplevel | None = None
        self._text_widget: tk.Text | None = None
        self._title: tk.Label | None = None
        self._provider: tk.Label | None = None
        self._preview: tk.Label | None = None
        self._status: tk.Label | None = None
        self._retry_btn: tk.Button | None = None
        self._pinned = False
        self._translated = ""
        self._source = ""
        self._anchor: tuple[int, int] = (0, 0)
        self._state = "idle"  # idle | loading | result | error

    # ------------------------------------------------------------ 状态
    @property
    def visible(self) -> bool:
        return self.top is not None and bool(self.top.winfo_exists())

    @property
    def pinned(self) -> bool:
        return self._pinned

    def rect(self) -> tuple[int, int, int, int] | None:
        if not self.visible:
            return None
        top = self.top
        return top.winfo_rootx(), top.winfo_rooty(), top.winfo_width(), top.winfo_height()

    def contains(self, x: int, y: int) -> bool:
        r = self.rect()
        if not r:
            return False
        rx, ry, rw, rh = r
        return rx <= x <= rx + rw and ry <= y <= ry + rh

    # ------------------------------------------------------------ 构建
    def _ensure_window(self) -> None:
        if self.visible:
            return
        fam = self.cfg.get("font_family", "Microsoft YaHei UI")
        size = int(self.cfg.get("font_size_px", -15))
        self._f_title = tkfont.Font(family=fam, size=-13, weight="bold")
        self._f_body = tkfont.Font(family=fam, size=size)
        self._f_small = tkfont.Font(family=fam, size=-12)

        top = tk.Toplevel(self.root)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        try:
            top.attributes("-alpha", 0.98)
        except tk.TclError:
            pass
        top.configure(bg=BORDER, padx=1, pady=1)

        outer = tk.Frame(top, bg=BG)
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=PANEL, height=34)
        header.pack(fill="x")
        header.pack_propagate(False)

        self._title = tk.Label(
            header, text="英 → 中文", bg=PANEL, fg=TEXT, font=self._f_title
        )
        self._title.pack(side="left", padx=(10, 6), pady=6)

        self._provider = tk.Label(
            header, text="", bg=PANEL, fg=MUTED, font=self._f_small
        )
        self._provider.pack(side="left")

        close_btn = tk.Label(header, text="✕", bg=PANEL, fg=MUTED, font=self._f_small,
                             padx=10, cursor="hand2")
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _e: self.hide())
        close_btn.bind("<Enter>", lambda _e: close_btn.configure(fg=WARN))
        close_btn.bind("<Leave>", lambda _e: close_btn.configure(fg=MUTED))

        pin_btn = tk.Label(header, text="固定", bg=PANEL, fg=MUTED, font=self._f_small,
                           padx=8, cursor="hand2")
        pin_btn.pack(side="right")
        pin_btn.bind("<Button-1>", lambda _e: self._toggle_pin(pin_btn))
        pin_btn.bind("<Enter>", lambda _e: pin_btn.configure(fg=TEXT))
        pin_btn.bind("<Leave>", lambda _e: self._set_pin_color(pin_btn))
        self._pin_btn_ref = pin_btn

        # 原文预览（两行以内）
        self._preview = tk.Label(
            outer, text="", bg=BG, fg=MUTED, font=self._f_small,
            justify="left", anchor="w", wraplength=self._width() - 24,
        )
        self._preview.pack(fill="x", padx=10, pady=(8, 0))

        body = tk.Frame(outer, bg=BG)
        body.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        self._text_widget = tk.Text(
            body, bg=BG, fg=TEXT, font=self._f_body, wrap="word",
            relief="flat", bd=0, highlightthickness=0,
            insertwidth=0, padx=4, pady=2, height=4,
            selectbackground=ACCENT, selectforeground="#0b0d11",
        )
        self._text_widget.pack(side="left", fill="both", expand=True)
        scroll = tk.Scrollbar(body, orient="vertical", command=self._text_widget.yview,
                              width=8, bg=PANEL, troughcolor=BG, bd=0,
                              activebackground=BORDER, relief="flat")
        scroll.pack(side="right", fill="y")
        self._text_widget.configure(yscrollcommand=scroll.set)
        self._text_widget.configure(state="disabled")

        footer = tk.Frame(outer, bg=BG, height=36)
        footer.pack(fill="x", padx=8, pady=(2, 8))
        footer.pack_propagate(False)

        self._status = tk.Label(footer, text="", bg=BG, fg=MUTED, font=self._f_small)
        self._status.pack(side="left", padx=4)

        self._retry_btn = tk.Button(
            footer, text="重新翻译", command=self._retry,
            bg=PANEL, fg=TEXT, activebackground=BORDER, activeforeground=TEXT,
            relief="flat", bd=0, font=self._f_small, padx=10, pady=3,
            cursor="hand2", highlightthickness=0,
        )
        self._retry_btn.pack(side="right", padx=(6, 2))
        self._copy_btn = tk.Button(
            footer, text="复制译文", command=self._copy,
            bg=ACCENT, fg="#0b0d11", activebackground=ACCENT_HOVER, activeforeground="#0b0d11",
            relief="flat", bd=0, font=self._f_small, padx=10, pady=3,
            cursor="hand2", highlightthickness=0,
        )
        self._copy_btn.pack(side="right")

        # 拖动 / 快捷键
        for widget in (header, self._title):
            widget.bind("<Button-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._on_drag)
        top.bind("<Escape>", lambda _e: self.hide())
        self._text_widget.bind("<MouseWheel>", self._on_wheel)
        self._text_widget.bind("<Control-c>", lambda _e: self._copy())

        self.top = top
        try:
            from .win32api import make_non_activating, root_hwnd

            self._own_hwnd = root_hwnd(top.winfo_id())
            make_non_activating(self._own_hwnd)
        except Exception:
            self._own_hwnd = 0

    # ------------------------------------------------------------ 尺寸/定位
    def _width(self) -> int:
        return int(self.cfg.get("popup_width", 640))

    def _max_height(self) -> int:
        return int(self.cfg.get("popup_max_height", 560))

    def _place(self, x: int, y: int) -> None:
        from .win32api import foreground_hwnd, monitor_work_area, restore_foreground

        top = self.top
        top.update_idletasks()
        w = self._width()
        # 先按内容估算高度，再夹进工作区
        needed = top.winfo_reqheight()
        max_h = self._max_height()
        h = max(160, min(needed, max_h))
        left, top_m, right, bottom = monitor_work_area(x, y)
        px = x + 14
        py = y + 18
        if px + w > right - 8:
            px = x - w - 14
        if px < left + 8:
            px = left + 8
        if py + h > bottom - 8:
            py = y - h - 18
        if py < top_m + 8:
            py = top_m + 8
        prev_fg = foreground_hwnd()
        top.geometry(f"{w}x{h}+{px}+{py}")
        self._anchor = (x, y)
        top.deiconify()
        top.lift()
        # 双保险：即使 Tk 在映射时激活了窗口，也把前台还给原应用
        if prev_fg and prev_fg != getattr(self, "_own_hwnd", 0):
            restore_foreground(prev_fg)

    def _fit_height(self) -> None:
        """按文本行数收缩高度，避免大段空白。"""
        if not self.visible or not self._text_widget:
            return
        top = self.top
        top.update_idletasks()
        try:
            lines = int(self._text_widget.count("1.0", "end", "displaylines")[0])
        except Exception:
            lines = 8
        line_h = max(14, int(self.cfg.get("font_size_px", -15)) * -1 + 6)
        body_h = max(60, min(lines + 1, 26) * line_h)
        preview_h = 20 if self._preview and self._preview.cget("text") else 0
        h = 34 + preview_h + body_h + 48
        h = min(h, self._max_height())
        top.update_idletasks()
        w = self._width()
        x = top.winfo_x()
        y = top.winfo_y()
        top.geometry(f"{w}x{h}+{x}+{y}")

    # ------------------------------------------------------------ 交互
    def _toggle_pin(self, btn: tk.Label) -> None:
        self._pinned = not self._pinned
        self._set_pin_color(btn)

    def _set_pin_color(self, btn: tk.Label) -> None:
        btn.configure(fg=ACCENT if self._pinned else MUTED,
                      text="已固定" if self._pinned else "固定")

    def _start_drag(self, event) -> None:
        self._drag_origin = (event.x_root, event.y_root)
        self._win_origin = (self.top.winfo_x(), self.top.winfo_y())

    def _on_drag(self, event) -> None:
        if not getattr(self, "_drag_origin", None):
            return
        dx = event.x_root - self._drag_origin[0]
        dy = event.y_root - self._drag_origin[1]
        self.top.geometry(f"+{self._win_origin[0] + dx}+{self._win_origin[1] + dy}")

    def _on_wheel(self, event) -> None:
        self._text_widget.yview_scroll(int(-event.delta / 120), "units")

    def _retry(self) -> None:
        if self._source:
            self.events.put(("retry", self._anchor[0], self._anchor[1], self._source))

    def _copy(self) -> None:
        if not self._translated:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self._translated)
        if self._status:
            self._status.configure(text="已复制", fg=OK)
            self.top.after(1500, lambda: self._status and self._status.configure(text="", fg=MUTED))

    # ------------------------------------------------------------ 内容
    def _set_body(self, text: str, fg: str = TEXT) -> None:
        widget = self._text_widget
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled", fg=fg)
        self._fit_height()

    def show_loading(self, x: int, y: int, source_preview: str = "") -> None:
        self._source = ""
        self._translated = ""
        self._ensure_window()
        self._state = "loading"
        self._title.configure(text="翻译中…")
        self._provider.configure(text="")
        self._preview.configure(text=source_preview, fg=MUTED)
        self._set_body("正在翻译…", MUTED)
        if self._status:
            self._status.configure(text="", fg=MUTED)
        if self._retry_btn:
            self._retry_btn.pack_forget()
        base = self._anchor if self.top and self.top.winfo_ismapped() else (x, y)
        self._place(x, y)

    def show_progress(self, done: int, total: int) -> None:
        if not self.visible:
            return
        if self._state == "loading" and self._status:
            self._status.configure(text=f"翻译中 {done}/{total}…", fg=MUTED)

    def show_result(self, translated: str, provider_label: str, source: str = "") -> None:
        if not self.visible:
            self._ensure_window()
        self._source = source
        self._translated = translated
        self._state = "result"
        self._title.configure(text="译文")
        self._provider.configure(text=provider_label)
        self._set_body(translated, TEXT)
        if self._status:
            self._status.configure(text="", fg=MUTED)
        if self._retry_btn and not self._retry_btn.winfo_ismapped():
            self._retry_btn.pack(side="right", padx=(6, 2))
        self._fit_height()
        self._place(*self._anchor)

    def show_error(self, message: str) -> None:
        if not self.visible:
            self._ensure_window()
        self._state = "error"
        self._title.configure(text="翻译失败")
        self._provider.configure(text="")
        hint = "全部免费引擎都失败了。请检查网络，或点托盘「测试翻译引擎」看具体原因。"
        self._set_body(f"{message}\n\n{hint}", WARN)
        if self._status:
            self._status.configure(text="", fg=MUTED)
        if self._retry_btn and not self._retry_btn.winfo_ismapped():
            self._retry_btn.pack(side="right", padx=(6, 2))
        self._place(*self._anchor)

    def hide(self) -> None:
        if self.top is not None:
            try:
                self.top.destroy()
            except tk.TclError:
                pass
            self.top = None
            self._text_widget = None
        self._pinned = False
        self._state = "idle"


class ModeDialog:
    """启动时选择「常驻 / 挂机」。"""

    WIDTH = 460
    HEIGHT = 300

    def __init__(self, root: tk.Tk, cfg, on_choose):
        self.root = root
        self.cfg = cfg
        self.on_choose = on_choose
        fam = cfg.get("font_family", "Microsoft YaHei UI")

        win = tk.Toplevel(root)
        win.title("划词翻译")
        win.configure(bg=BG)
        win.resizable(False, False)
        win.attributes("-topmost", True)

        w, h = self.WIDTH, self.HEIGHT
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")

        tk.Label(win, text="选择启动状态", bg=BG, fg=TEXT,
                 font=(fam, -18, "bold")).pack(pady=(20, 4))
        tk.Label(win, text="桌面划词翻译：选中英文后自动弹出中文译文",
                 bg=BG, fg=MUTED, font=(fam, -12)).pack()

        buttons = tk.Frame(win, bg=BG)
        buttons.pack(fill="x", padx=20, pady=16)

        def make_card(parent, title, desc, color, command):
            frame = tk.Frame(parent, bg=PANEL, padx=14, pady=12, cursor="hand2")
            frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
            tk.Label(frame, text=title, bg=PANEL, fg=color,
                     font=(fam, -14, "bold"), anchor="w").pack(fill="x")
            tk.Label(frame, text=desc, bg=PANEL, fg=MUTED, font=(fam, -11),
                     justify="left", anchor="w").pack(fill="x", pady=(4, 0))
            for widget in (frame, *frame.winfo_children()):
                widget.bind("<Button-1>", lambda _e, c=command: c())

        make_card(buttons, "常驻", "安装全局钩子\n选中英文即自动翻译", ACCENT,
                  lambda: self._choose("on"))
        make_card(buttons, "挂机", "只驻留托盘\n不监听鼠标，不翻译", MUTED,
                  lambda: self._choose("idle"))

        self.remember = tk.BooleanVar(value=True)
        tk.Checkbutton(win, text="记住选择，下次启动不再询问", variable=self.remember,
                       bg=BG, fg=MUTED, activebackground=BG, activeforeground=TEXT,
                       selectcolor=PANEL, font=(fam, -11),
                       highlightthickness=0, bd=0).pack(pady=(0, 6))
        tk.Label(win, text="托盘右键可随时在「常驻 / 挂机」之间切换",
                 bg=BG, fg=MUTED, font=(fam, -10)).pack(pady=(0, 10))

        win.protocol("WM_DELETE_WINDOW", lambda: self._choose("idle"))
        win.after(50, lambda: win.lift())
        self.win = win
        win.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        self._choose("idle")

    def _choose(self, mode: str) -> None:
        remember = bool(self.remember.get())
        self.cfg.set("mode", mode)
        self.cfg.set("ask_mode_on_start", not remember)
        self.cfg.save()
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        self.on_choose(mode)



