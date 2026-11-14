"""
Typed ctypes prototypes for every Win32 call the Windows adapter makes.

`ctypes.windll.user32.Foo(...)` without `argtypes` marshals every Python int as
a 32-bit C `int`. Inside a `WH_KEYBOARD_LL` / `WH_MOUSE_LL` callback the
`lParam` is a pointer to a struct on the hook thread's stack, which on x64
lives above 4 GiB, so an untyped `CallNextHookEx(..., l_param)` raises
`ArgumentError: int too long to convert` on *every* event. The exception
unwinds through the ctypes thunk, the hook returns garbage, and the hook
chain is cut for every other process on the machine. Declaring the
prototypes once here, and importing the functions from this module, makes
that class of bug impossible.

Every symbol in this module is `None` off Windows so the adapter files can be
imported (and unit-tested) on macOS/Linux; callers already guard with
`sys.platform == "win32"`.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Any, Final

IS_WINDOWS: Final[bool] = sys.platform == "win32"

# Declared `Any` because these are real ctypes objects on Windows and `None`
# everywhere else; the adapter code only touches them behind `IS_WINDOWS`.
user32: Any
kernel32: Any
HOOKPROC: Any
WNDPROC: Any
MSG: Any

if IS_WINDOWS:
    import ctypes.wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wt.DWORD),
            ("scanCode", wt.DWORD),
            ("flags", wt.DWORD),
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

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wt.LONG),
            ("dy", wt.LONG),
            ("mouseData", wt.DWORD),
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

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wt.DWORD), ("union", _INPUT_UNION)]

    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [
            ("usUsagePage", wt.USHORT),
            ("usUsage", wt.USHORT),
            ("dwFlags", wt.DWORD),
            ("hwndTarget", wt.HWND),
        ]

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [
            ("dwType", wt.DWORD),
            ("dwSize", wt.DWORD),
            ("hDevice", wt.HANDLE),
            ("wParam", wt.WPARAM),
        ]

    class RAWMOUSE(ctypes.Structure):
        _fields_ = [
            ("usFlags", wt.USHORT),
            ("_pad", wt.USHORT),
            ("usButtonFlags", wt.USHORT),
            ("usButtonData", wt.USHORT),
            ("ulRawButtons", wt.ULONG),
            ("lLastX", wt.LONG),
            ("lLastY", wt.LONG),
            ("ulExtraInformation", wt.ULONG),
        ]

    class RAWINPUT_MOUSE(ctypes.Structure):
        _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wt.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wt.HINSTANCE),
            ("hIcon", wt.HICON),
            ("hCursor", wt.HANDLE),
            ("hbrBackground", wt.HBRUSH),
            ("lpszMenuName", wt.LPCWSTR),
            ("lpszClassName", wt.LPCWSTR),
        ]

    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wt.DWORD),
            ("flags", wt.DWORD),
            ("hwndActive", wt.HWND),
            ("hwndFocus", wt.HWND),
            ("hwndCapture", wt.HWND),
            ("hwndMenuOwner", wt.HWND),
            ("hwndMoveSize", wt.HWND),
            ("hwndCaret", wt.HWND),
            ("rcCaret", wt.RECT),
        ]

    # --- hooks -------------------------------------------------------------
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
    user32.SetWindowsHookExW.restype = wt.HHOOK
    user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
    user32.UnhookWindowsHookEx.restype = wt.BOOL

    # --- message loop ------------------------------------------------------
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    user32.GetMessageW.restype = wt.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.TranslateMessage.restype = wt.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.PostThreadMessageW.restype = wt.BOOL
    user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.PostMessageW.restype = wt.BOOL
    user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t

    # --- message-only window + raw input ---------------------------------
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wt.ATOM
    user32.UnregisterClassW.argtypes = [wt.LPCWSTR, wt.HINSTANCE]
    user32.UnregisterClassW.restype = wt.BOOL
    user32.CreateWindowExW.argtypes = [
        wt.DWORD,
        wt.LPCWSTR,
        wt.LPCWSTR,
        wt.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wt.HWND,
        wt.HMENU,
        wt.HINSTANCE,
        wt.LPVOID,
    ]
    user32.CreateWindowExW.restype = wt.HWND
    user32.DestroyWindow.argtypes = [wt.HWND]
    user32.DestroyWindow.restype = wt.BOOL
    user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wt.UINT, wt.UINT]
    user32.RegisterRawInputDevices.restype = wt.BOOL
    user32.GetRawInputData.argtypes = [
        wt.HANDLE,
        wt.UINT,
        wt.LPVOID,
        ctypes.POINTER(wt.UINT),
        wt.UINT,
    ]
    user32.GetRawInputData.restype = wt.UINT

    # --- hotkeys / key state ----------------------------------------------
    user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
    user32.RegisterHotKey.restype = wt.BOOL
    user32.UnregisterHotKey.argtypes = [wt.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wt.BOOL
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetKeyboardLayout.argtypes = [wt.DWORD]
    user32.GetKeyboardLayout.restype = wt.HKL
    user32.ToUnicodeEx.argtypes = [
        wt.UINT,
        wt.UINT,
        ctypes.POINTER(ctypes.c_ubyte),
        wt.LPWSTR,
        ctypes.c_int,
        wt.UINT,
        wt.HKL,
    ]
    user32.ToUnicodeEx.restype = ctypes.c_int

    # --- windows / focus ---------------------------------------------------
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetGUIThreadInfo.argtypes = [wt.DWORD, ctypes.POINTER(GUITHREADINFO)]
    user32.GetGUIThreadInfo.restype = wt.BOOL
    user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wt.LONG
    user32.GetKeyState.argtypes = [ctypes.c_int]
    user32.GetKeyState.restype = ctypes.c_short
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.SendMessageTimeoutW.argtypes = [
        wt.HWND,
        wt.UINT,
        wt.WPARAM,
        wt.LPARAM,
        wt.UINT,
        wt.UINT,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    user32.SendMessageTimeoutW.restype = wt.LPARAM
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsWindowVisible.restype = wt.BOOL
    user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
    user32.ClientToScreen.restype = wt.BOOL
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wt.BOOL
    user32.SetWindowPos.argtypes = [
        wt.HWND,
        wt.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wt.UINT,
    ]
    user32.SetWindowPos.restype = wt.BOOL
    try:
        user32.GetDpiForWindow.argtypes = [wt.HWND]
        user32.GetDpiForWindow.restype = wt.UINT
    except Exception:
        pass

    # --- injection ---------------------------------------------------------
    user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wt.UINT

    # --- kernel32 ----------------------------------------------------------
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wt.DWORD
    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wt.HMODULE
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    kernel32.GetExitCodeProcess.restype = wt.BOOL
    kernel32.TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
    kernel32.TerminateProcess.restype = wt.BOOL
    kernel32.CloseHandle.argtypes = [wt.HANDLE]
    kernel32.CloseHandle.restype = wt.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wt.HANDLE,
        wt.DWORD,
        wt.LPWSTR,
        ctypes.POINTER(wt.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
    kernel32.CreateMutexW.argtypes = [wt.LPVOID, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateMutexW.restype = wt.HANDLE
    kernel32.ReleaseMutex.argtypes = [wt.HANDLE]
    kernel32.ReleaseMutex.restype = wt.BOOL
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wt.DWORD

    MSG = wt.MSG
else:  # pragma: no cover - exercised only off Windows
    user32 = None
    kernel32 = None
    HOOKPROC = None
    WNDPROC = None
    MSG = None
    KBDLLHOOKSTRUCT = None  # type: ignore[assignment,misc]
    KEYBDINPUT = None  # type: ignore[assignment,misc]
    MOUSEINPUT = None  # type: ignore[assignment,misc]
    HARDWAREINPUT = None  # type: ignore[assignment,misc]
    INPUT = None  # type: ignore[assignment,misc]
    RAWINPUTDEVICE = None  # type: ignore[assignment,misc]
    RAWINPUTHEADER = None  # type: ignore[assignment,misc]
    RAWMOUSE = None  # type: ignore[assignment,misc]
    RAWINPUT_MOUSE = None  # type: ignore[assignment,misc]
    WNDCLASSW = None  # type: ignore[assignment,misc]
    GUITHREADINFO = None  # type: ignore[assignment,misc]


def last_error() -> int:
    """`GetLastError()` as captured by ctypes for the calling thread (0 off Windows)."""
    if not IS_WINDOWS:
        return 0
    return int(ctypes.get_last_error())


def win_error_message(code: int) -> str:
    if not IS_WINDOWS:
        return f"error {code}"
    try:
        return f"{ctypes.FormatError(code).strip()} (error {code})"
    except Exception:
        return f"error {code}"


# Well-known constants shared by the adapter modules.
WH_KEYBOARD_LL: Final[int] = 13
WM_KEYDOWN: Final[int] = 0x0100
WM_SYSKEYDOWN: Final[int] = 0x0104
WM_QUIT: Final[int] = 0x0012
WM_HOTKEY: Final[int] = 0x0312
WM_INPUT: Final[int] = 0x00FF
WM_APP: Final[int] = 0x8000
HC_ACTION: Final[int] = 0
LLKHF_INJECTED: Final[int] = 0x00000010
HWND_MESSAGE: Final[int] = -3
RIDEV_INPUTSINK: Final[int] = 0x00000100
RIM_TYPEMOUSE: Final[int] = 0
RID_INPUT: Final[int] = 0x10000003
RI_MOUSE_LEFT_BUTTON_DOWN: Final[int] = 0x0001
RI_MOUSE_RIGHT_BUTTON_DOWN: Final[int] = 0x0004
RI_MOUSE_MIDDLE_BUTTON_DOWN: Final[int] = 0x0010
RI_MOUSE_ANY_BUTTON_DOWN: Final[int] = (
    RI_MOUSE_LEFT_BUTTON_DOWN | RI_MOUSE_RIGHT_BUTTON_DOWN | RI_MOUSE_MIDDLE_BUTTON_DOWN
)
HID_USAGE_PAGE_GENERIC: Final[int] = 0x01
HID_USAGE_GENERIC_MOUSE: Final[int] = 0x02
MOD_ALT: Final[int] = 0x0001
MOD_CONTROL: Final[int] = 0x0002
MOD_SHIFT: Final[int] = 0x0004
MOD_WIN: Final[int] = 0x0008
MOD_NOREPEAT: Final[int] = 0x4000
INPUT_KEYBOARD: Final[int] = 1
KEYEVENTF_KEYUP: Final[int] = 0x0002
KEYEVENTF_UNICODE: Final[int] = 0x0004
PROCESS_QUERY_LIMITED_INFORMATION: Final[int] = 0x1000
PROCESS_TERMINATE: Final[int] = 0x0001
STILL_ACTIVE: Final[int] = 259
ERROR_ALREADY_EXISTS: Final[int] = 183
ES_PASSWORD: Final[int] = 0x0020
GWL_STYLE: Final[int] = -16


def lparam_fits_untyped_int(value: int) -> bool:
    """
    True when `value` would survive ctypes' default (32-bit int) marshalling.
    Exists so a unit test can document the bug the typed prototypes fix.
    """
    return -(2**31) <= value < 2**31
