"""Windows 底层能力（纯 ctypes，无第三方依赖）。

包含：
- 进程 DPI 感知
- 全局低层鼠标钩子（WH_MOUSE_LL）
- 托盘图标（Shell_NotifyIcon）+ 隐藏窗口消息循环 + 弹出菜单
- 全局热键（RegisterHotKey）
- 剪贴板读写与序号、Ctrl+C 注入（SendInput）
- 光标 / 前台进程 / 显示器工作区

设计：所有 Win32 对象都在一个专用线程里创建并泵消息；外部线程只通过
PostMessageW 与该线程通信，事件通过 queue 交给 tkinter 主线程消费。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import queue
import threading
import time
from ctypes import POINTER, byref, c_int, c_ssize_t, c_ubyte, c_uint, c_ulong, c_ushort, c_void_p, c_wchar_p

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 类型别名
HANDLE = c_void_p
HWND = HANDLE
HICON = HANDLE
HMENU = HANDLE
HINSTANCE = HANDLE
HMODULE = HANDLE
HGLOBAL = HANDLE
HBRUSH = HANDLE
ATOM = c_ushort
LRESULT = c_ssize_t

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, c_int, wt.WPARAM, wt.LPARAM)


# ---------------------------------------------------------------- 结构体
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wt.DWORD),
        ("Data2", wt.WORD),
        ("Data3", wt.WORD),
        ("Data4", c_ubyte * 8),
    ]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", c_int),
        ("cbWndExtra", c_int),
        ("hInstance", HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HANDLE),
        ("hbrBackground", HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", HICON),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", HICON),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wt.DWORD),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wt.DWORD),
        ("wParamL", wt.WORD),
        ("wParamH", wt.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


# ---------------------------------------------------------------- 常量
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_C = 0x43
VK_T = 0x54

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

WH_MOUSE_LL = 14
HC_ACTION = 0
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207

WM_CLOSE = 0x0010
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_HOTKEY = 0x0312
WM_NULL = 0x0000
WM_APP = 0x8000
WM_TRAY = WM_APP + 10
WM_SET_MODE = WM_APP + 2
WM_PING = WM_APP + 1
WM_NOTIFY = WM_APP + 3

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04
NIF_INFO = 0x10
NIIF_INFO = 0x01

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
TPM_RIGHTBUTTON = 0x0002
TPM_LEFTALIGN = 0x0000

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

MONITOR_DEFAULTTONEAREST = 2

# 窗口扩展样式 / 鼠标注入
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
GA_ROOT = 2
INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# 托盘菜单 ID
MENU_RESIDENT = 1001
MENU_IDLE = 1002
MENU_TRANSLATE_CLIPBOARD = 1010
MENU_TEST_ENGINE = 1020
MENU_RELOAD_CONFIG = 1030
MENU_OPEN_CONFIG_DIR = 1040
MENU_EXIT = 1050
HOTKEY_ID = 1


# ---------------------------------------------------------------- 函数原型
def _init_prototypes() -> None:
    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    kernel32.GetModuleHandleW.restype = HMODULE

    user32.RegisterClassW.argtypes = [POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = ATOM
    user32.CreateWindowExW.argtypes = [
        wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
        c_int, c_int, c_int, c_int,
        HWND, HMENU, HINSTANCE, c_void_p,
    ]
    user32.CreateWindowExW.restype = HWND
    user32.DefWindowProcW.argtypes = [HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.DestroyWindow.argtypes = [HWND]
    user32.PostMessageW.argtypes = [HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.GetMessageW.argtypes = [POINTER(wt.MSG), HWND, wt.UINT, wt.UINT]
    user32.GetMessageW.restype = c_int
    user32.TranslateMessage.argtypes = [POINTER(wt.MSG)]
    user32.DispatchMessageW.argtypes = [POINTER(wt.MSG)]
    user32.DispatchMessageW.restype = LRESULT

    user32.SetWindowsHookExW.argtypes = [c_int, HOOKPROC, HINSTANCE, wt.DWORD]
    user32.SetWindowsHookExW.restype = HANDLE
    user32.UnhookWindowsHookEx.argtypes = [HANDLE]
    user32.CallNextHookEx.argtypes = [HANDLE, c_int, wt.WPARAM, wt.LPARAM]
    user32.CallNextHookEx.restype = LRESULT

    user32.RegisterHotKey.argtypes = [HWND, c_int, wt.UINT, wt.UINT]
    user32.UnregisterHotKey.argtypes = [HWND, c_int]

    shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, POINTER(NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wt.BOOL
    user32.LoadImageW.argtypes = [HINSTANCE, wt.LPCWSTR, wt.UINT, c_int, c_int, wt.UINT]
    user32.LoadImageW.restype = HANDLE
    user32.DestroyIcon.argtypes = [HICON]

    user32.CreatePopupMenu.restype = HMENU
    user32.AppendMenuW.argtypes = [HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
    user32.TrackPopupMenu.argtypes = [HMENU, wt.UINT, c_int, c_int, c_int, HWND, c_void_p]
    user32.TrackPopupMenu.restype = wt.BOOL
    user32.DestroyMenu.argtypes = [HMENU]
    user32.SetForegroundWindow.argtypes = [HWND]

    user32.GetCursorPos.argtypes = [POINTER(POINT)]
    user32.SetCursorPos.argtypes = [c_int, c_int]
    user32.SetCursorPos.restype = wt.BOOL
    user32.GetAncestor.argtypes = [HWND, wt.UINT]
    user32.GetAncestor.restype = HWND
    user32.GetWindowLongW.argtypes = [HWND, c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [HWND, c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
    user32.FindWindowW.restype = HWND
    user32.GetForegroundWindow.restype = HWND
    user32.GetWindowThreadProcessId.argtypes = [HWND, POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.GetWindowRect.argtypes = [HWND, POINTER(RECT)]
    user32.MonitorFromPoint.argtypes = [POINT, wt.DWORD]
    user32.MonitorFromPoint.restype = HANDLE
    user32.GetMonitorInfoW.argtypes = [HANDLE, POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wt.BOOL
    user32.GetAsyncKeyState.argtypes = [c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short

    user32.SendInput.argtypes = [wt.UINT, POINTER(INPUT), c_int]
    user32.SendInput.restype = wt.UINT

    user32.SetProcessDPIAware.argtypes = []
    user32.SetProcessDPIAware.restype = wt.BOOL
    try:  # Win10 1703+；旧系统没有该导出，set_dpi_aware 会回退
        user32.SetProcessDpiAwarenessContext.argtypes = [c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = wt.BOOL
    except AttributeError:
        pass

    user32.OpenClipboard.argtypes = [HWND]
    user32.CloseClipboard.argtypes = []
    user32.EmptyClipboard.argtypes = []
    user32.GetClipboardData.argtypes = [wt.UINT]
    user32.GetClipboardData.restype = HANDLE
    user32.SetClipboardData.argtypes = [wt.UINT, HANDLE]
    user32.SetClipboardData.restype = HANDLE
    user32.GetClipboardSequenceNumber.restype = wt.DWORD
    user32.IsClipboardFormatAvailable.argtypes = [wt.UINT]
    user32.IsClipboardFormatAvailable.restype = wt.BOOL

    kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = HGLOBAL
    kernel32.GlobalLock.argtypes = [HGLOBAL]
    kernel32.GlobalLock.restype = c_void_p
    kernel32.GlobalUnlock.argtypes = [HGLOBAL]
    kernel32.GetCurrentProcessId.restype = wt.DWORD


_init_prototypes()

_PROCESS_ID = kernel32.GetCurrentProcessId()


# ---------------------------------------------------------------- DPI
def set_dpi_aware() -> None:
    """让 Win32 坐标、tkinter 几何、截图像素保持一致（物理像素）。"""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


# ---------------------------------------------------------------- 查询
def cursor_pos() -> tuple[int, int]:
    p = POINT()
    user32.GetCursorPos(byref(p))
    return p.x, p.y


def foreground_pid() -> int:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return 0
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, byref(pid))
    return pid.value


def is_own_foreground() -> bool:
    return foreground_pid() == _PROCESS_ID


def foreground_hwnd() -> int:
    return int(user32.GetForegroundWindow() or 0)


def restore_foreground(hwnd: int) -> None:
    """尽力把前台交还给之前的窗口（失败无副作用）。"""
    if not hwnd:
        return
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def root_hwnd(hwnd: int) -> int:
    try:
        root = int(user32.GetAncestor(hwnd, GA_ROOT) or 0)
        return root or hwnd
    except Exception:
        return hwnd


def make_non_activating(hwnd: int) -> None:
    """给浮窗加 WS_EX_NOACTIVATE：显示/点击都不会抢走前台焦点。"""
    try:
        target = root_hwnd(hwnd)
        style = int(user32.GetWindowLongW(target, GWL_EXSTYLE))
        user32.SetWindowLongW(
            target, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        )
    except Exception:
        log.warning("设置 WS_EX_NOACTIVATE 失败", exc_info=True)


def mouse_click(x: int, y: int) -> None:
    """真实鼠标点击（selftest/联调用）。"""
    user32.SetCursorPos(x, y)
    time.sleep(0.03)
    for flag in (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP):
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flag, time=0, dwExtraInfo=0)
        user32.SendInput(1, byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.03)


def monitor_work_area(x: int, y: int) -> tuple[int, int, int, int]:
    """返回 (left, top, right, bottom) 工作区（不含任务栏）。"""
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    hmon = user32.MonitorFromPoint(POINT(x, y), MONITOR_DEFAULTTONEAREST)
    if hmon and user32.GetMonitorInfoW(hmon, byref(mi)):
        r = mi.rcWork
        return r.left, r.top, r.right, r.bottom
    return 0, 0, 1920, 1080


def window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    r = RECT()
    if user32.GetWindowRect(hwnd, byref(r)):
        return r.left, r.top, r.right, r.bottom
    return None


# ---------------------------------------------------------------- 剪贴板
class Clipboard:
    @staticmethod
    def _open(retries: int = 15) -> bool:
        for _ in range(retries):
            if user32.OpenClipboard(None):
                return True
            time.sleep(0.02)
        return False

    @classmethod
    def get_text(cls) -> str | None:
        if not cls._open():
            return None
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return None
            try:
                return ctypes.wstring_at(ptr)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    @classmethod
    def set_text(cls, text: str) -> bool:
        if not cls._open():
            return False
        try:
            user32.EmptyClipboard()
            data = (text + "\0").encode("utf-16-le")
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not handle:
                return False
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                return False
            ctypes.memmove(ptr, data, len(data))
            kernel32.GlobalUnlock(handle)
            return bool(user32.SetClipboardData(CF_UNICODETEXT, handle))
        finally:
            user32.CloseClipboard()

    @staticmethod
    def sequence_number() -> int:
        return int(user32.GetClipboardSequenceNumber())

    @staticmethod
    def has_text() -> bool:
        return bool(user32.IsClipboardFormatAvailable(CF_UNICODETEXT))


# ---------------------------------------------------------------- 输入注入
def _send_key(vk: int, up: bool = False) -> None:
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(
        wVk=vk,
        wScan=0,
        dwFlags=KEYEVENTF_KEYUP if up else 0,
        time=0,
        dwExtraInfo=0,
    )
    user32.SendInput(1, byref(inp), ctypes.sizeof(INPUT))


def send_ctrl_c() -> None:
    """模拟 Ctrl+C；若用户正按住 Ctrl 则只补发 C，避免修饰键状态错乱。"""
    ctrl_down = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
    if not ctrl_down:
        _send_key(VK_CONTROL)
        time.sleep(0.012)
    _send_key(VK_C)
    time.sleep(0.012)
    _send_key(VK_C, up=True)
    if not ctrl_down:
        time.sleep(0.012)
        _send_key(VK_CONTROL, up=True)


# ---------------------------------------------------------------- Win32 服务线程
class WinService:
    """隐藏窗口 + 托盘 + 全局鼠标钩子 + 热键，运行在独立线程。

    通过 ``events`` 队列向主线程投递：
      ("drag", x, y)            完成一次拖选（松开）
      ("mousedown", x, y)       任意左键按下（用于关闭浮窗）
      ("hotkey",)               全局热键
      ("menu", menu_id)         托盘菜单点击
      ("tray_click",)           左键单击托盘
      ("second_instance",)      重复启动
    """

    CLASS_NAME = "MouseTranslateTrayWnd"

    def __init__(self, events: queue.Queue, icon_paths: dict, min_drag_px: int = 6):
        self.events = events
        self.icon_paths = icon_paths
        self.min_drag2 = min_drag_px * min_drag_px
        self.hwnd: int | None = None
        self._thread: threading.Thread | None = None
        self._hook = None
        self._hook_proc = None
        self._wndproc = None
        self._down: tuple[int, int] | None = None
        self._resident = False
        self._nid: NOTIFYICONDATAW | None = None
        self._icon_on = None
        self._icon_off = None
        self._hotkey_ok = False
        self._pending_notify: list[tuple[str, str]] = []
        self._ready = threading.Event()

    # ------------------------------------------------------------ 生命周期
    def start(self, timeout: float = 5.0) -> bool:
        self._thread = threading.Thread(target=self._run, name="win32-service", daemon=True)
        self._thread.start()
        return self._ready.wait(timeout)

    def shutdown(self) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def wait(self) -> None:
        if self._thread:
            self._thread.join(timeout=3)

    # ------------------------------------------------------------ 外部线程调用
    def post_set_mode(self, resident: bool) -> None:
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_SET_MODE, 1 if resident else 0, 0)

    def post_notify(self, title: str, message: str) -> None:
        if self.hwnd:
            self._pending_notify.append((title, message))
            user32.PostMessageW(self.hwnd, WM_NOTIFY, 0, 0)

    # ------------------------------------------------------------ 线程主体
    def _run(self) -> None:
        try:
            hinst = kernel32.GetModuleHandleW(None)
            self._wndproc = WNDPROC(self._on_message)
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinst
            wc.lpszClassName = self.CLASS_NAME
            if not user32.RegisterClassW(byref(wc)):
                err = ctypes.get_last_error()
                if err not in (0, 1410):  # 1410 = class already exists
                    raise OSError(f"RegisterClassW failed: {err}")
            self.hwnd = user32.CreateWindowExW(
                0, self.CLASS_NAME, "MouseTranslate", 0,
                0, 0, 0, 0, None, None, hinst, None,
            )
            if not self.hwnd:
                raise OSError(f"CreateWindowExW failed: {ctypes.get_last_error()}")
            self._icon_on = self._load_icon(self.icon_paths["on"])
            self._icon_off = self._load_icon(self.icon_paths["off"])
            self._add_tray()
            self._register_hotkey()
            self._ready.set()

            msg = wt.MSG()
            while True:
                ret = user32.GetMessageW(byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                user32.TranslateMessage(byref(msg))
                user32.DispatchMessageW(byref(msg))
        except Exception:
            log.exception("Win32 服务线程异常")
            self.events.put(("service_error", "Win32 服务线程异常，详见日志"))
        finally:
            self._ready.set()
            self._cleanup()

    def _cleanup(self) -> None:
        try:
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None
            if self.hwnd:
                user32.UnregisterHotKey(self.hwnd, HOTKEY_ID)
            if self._nid:
                shell32.Shell_NotifyIconW(NIM_DELETE, byref(self._nid))
                self._nid = None
            for icon in (self._icon_on, self._icon_off):
                if icon:
                    user32.DestroyIcon(icon)
            self._icon_on = self._icon_off = None
            if self.hwnd:
                user32.DestroyWindow(self.hwnd)
                self.hwnd = None
        except Exception:
            log.exception("清理 Win32 资源失败")

    # ------------------------------------------------------------ 消息循环
    def _on_message(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_SET_MODE:
                self._set_resident(bool(wparam))
                return 0
            if msg == WM_PING:
                self.events.put(("second_instance",))
                return 0
            if msg == WM_HOTKEY:
                self.events.put(("hotkey",))
                return 0
            if msg == WM_TRAY:
                ev = lparam & 0xFFFF
                if ev == WM_LBUTTONUP:
                    self.events.put(("tray_click",))
                elif ev == WM_RBUTTONUP:
                    self._show_menu()
                return 0
            if msg == WM_COMMAND:
                self.events.put(("menu", wparam & 0xFFFF))
                return 0
            if msg == WM_NOTIFY:
                while self._pending_notify:
                    title, text = self._pending_notify.pop(0)
                    self._balloon(title, text)
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("消息处理异常 msg=0x%x", msg)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    # ------------------------------------------------------------ 托盘
    def _load_icon(self, path):
        return user32.LoadImageW(None, str(path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE)

    def _add_tray(self) -> None:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = self._icon_off
        nid.szTip = "划词翻译 · 挂机"
        shell32.Shell_NotifyIconW(NIM_ADD, byref(nid))
        self._nid = nid
        log.info("托盘图标已创建（当前状态：挂机）")

    def _refresh_tray(self) -> None:
        if not self._nid:
            return
        self._nid.hIcon = self._icon_on if self._resident else self._icon_off
        self._nid.szTip = "划词翻译 · 常驻" if self._resident else "划词翻译 · 挂机"
        self._nid.uFlags = NIF_ICON | NIF_TIP
        shell32.Shell_NotifyIconW(NIM_MODIFY, byref(self._nid))

    def _balloon(self, title: str, text: str) -> None:
        if not self._nid:
            return
        nid = self._nid
        nid.uFlags = NIF_INFO
        nid.szInfoTitle = title[:63]
        nid.szInfo = text[:255]
        nid.dwInfoFlags = NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, byref(nid))
        # 还原图标提示，避免下次 modify 丢图标
        self._nid = nid
        self._refresh_tray()

    def _show_menu(self) -> None:
        menu = user32.CreatePopupMenu()
        if not menu:
            return
        try:
            flags_res = MF_STRING | (MF_CHECKED if self._resident else 0)
            flags_idle = MF_STRING | (MF_CHECKED if not self._resident else 0)
            user32.AppendMenuW(menu, flags_res, MENU_RESIDENT, "常驻（划词自动翻译）")
            user32.AppendMenuW(menu, flags_idle, MENU_IDLE, "挂机（暂停监听）")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_TRANSLATE_CLIPBOARD, "翻译剪贴板内容\tCtrl+Alt+T")
            user32.AppendMenuW(menu, MF_STRING, MENU_TEST_ENGINE, "测试翻译引擎…")
            user32.AppendMenuW(menu, MF_STRING, MENU_RELOAD_CONFIG, "重新载入配置")
            user32.AppendMenuW(menu, MF_STRING, MENU_OPEN_CONFIG_DIR, "打开配置文件夹")
            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(menu, MF_STRING, MENU_EXIT, "退出")
            x, y = cursor_pos()
            user32.SetForegroundWindow(self.hwnd)
            user32.TrackPopupMenu(
                menu, TPM_RIGHTBUTTON | TPM_LEFTALIGN, x, y, 0, self.hwnd, None
            )
            user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        finally:
            user32.DestroyMenu(menu)

    # ------------------------------------------------------------ 热键
    def _register_hotkey(self) -> None:
        mods = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
        if user32.RegisterHotKey(self.hwnd, HOTKEY_ID, mods, VK_T):
            self._hotkey_ok = True
            log.info("全局热键 Ctrl+Alt+T 注册成功")
        else:
            log.warning("RegisterHotKey 失败（可能被其他程序占用）")
            self.events.put(("hotkey_failed",))

    # ------------------------------------------------------------ 钩子
    def _set_resident(self, resident: bool) -> None:
        self._resident = resident
        log.info("切换到%s", "常驻（监听划词）" if resident else "挂机（暂停监听）")
        if resident:
            self._install_hook()
        else:
            self._uninstall_hook()
        self._refresh_tray()

    def _install_hook(self) -> None:
        if self._hook:
            return
        self._hook_proc = HOOKPROC(self._on_mouse)
        self._hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._hook_proc, kernel32.GetModuleHandleW(None), 0
        )
        if not self._hook:
            log.error("SetWindowsHookExW 失败: %s", ctypes.get_last_error())
            self.events.put(("hook_failed",))
        else:
            log.info("全局鼠标钩子已安装")

    def _uninstall_hook(self) -> None:
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
            log.info("全局鼠标钩子已卸载")
        self._down = None

    def _on_mouse(self, ncode, wparam, lparam):
        if ncode >= 0:
            try:
                if wparam == WM_LBUTTONDOWN:
                    info = ctypes.cast(lparam, POINTER(MSLLHOOKSTRUCT)).contents
                    self._down = (info.pt.x, info.pt.y)
                    self.events.put(("mousedown", info.pt.x, info.pt.y))
                elif wparam == WM_LBUTTONUP:
                    info = ctypes.cast(lparam, POINTER(MSLLHOOKSTRUCT)).contents
                    down = self._down
                    self._down = None
                    if down:
                        dx = info.pt.x - down[0]
                        dy = info.pt.y - down[1]
                        if dx * dx + dy * dy >= self.min_drag2:
                            self.events.put(("drag", info.pt.x, info.pt.y))
            except Exception:
                log.exception("鼠标钩子回调异常")
        return user32.CallNextHookEx(None, ncode, wparam, lparam)




