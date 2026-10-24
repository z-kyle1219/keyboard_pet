"""一键最小化：把桌面上所有可见窗口最小化，只保留桌宠自己。

设计取舍（2026-10-24）：
- 纯单向：只做最小化，不做还原，因此没有状态、没有句柄缓存，
  逻辑短且无副作用。
- 用 EnumWindows + ShowWindowAsync(SW_MINIMIZE) 而不是模拟 Win+D：
  前者精确可控，能排除本进程窗口，也不会被输入法/安全软件吞掉。
- 用 ShowWindowAsync 而非同步的 ShowWindow：后者会给目标窗口的线程
  发消息并等待，若某个程序卡死无响应，右键菜单会跟着卡住；
  Async 版本只投递请求立即返回，语义相同但不阻塞界面。
- 作为 Mixin 混入 PetApp，self 语义保持不变。

已知限制（无法规避，见 README）：
- Windows UIPI 机制会拦截跨权限的窗口操作：本程序以普通权限运行时，
  无法最小化以管理员身份运行的窗口（如“以管理员运行”的终端、任务
  管理器）。这些窗口会被静默跳过，ShowWindowAsync 不报错也不生效。
- 其它虚拟桌面上的传统 Win32 程序不会被 cloaked 标记，也会被一并
  最小化（仅让那些桌面多出若干最小化窗口，影响可接受）。
"""
import ctypes
import os
from ctypes import wintypes

from logger import logger

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

# ---------- Win32 常量 ----------
SW_MINIMIZE = 6
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
DWMWA_CLOAKED = 14

# 系统外壳窗口（桌面 / 任务栏），最小化它们没意义且可能出怪现象，直接跳过
_SKIP_CLASSES = {
    'Progman',              # 桌面
    'WorkerW',              # 桌面壁纸层
    'Shell_TrayWnd',        # 主任务栏
    'Shell_SecondaryTrayWnd',  # 副屏任务栏
}

# ---------- 函数签名（显式声明，避免 64 位下指针截断）----------
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindowAsync.restype = wintypes.BOOL
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = wintypes.LONG
user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
dwmapi.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

_ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [_ENUM_PROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL


def _class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _is_cloaked(hwnd):
    """UWP 窗口在其它虚拟桌面/最小化时会处于 cloaked 状态。

    cloaked 的窗口虽然 IsWindowVisible 仍为真，但实际不可见，
    最小化它们会误伤别的虚拟桌面，故一并跳过。
    """
    value = ctypes.c_int(0)
    try:
        dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        return False
    return value.value != 0


class MinimizeMixin:
    """提供 _minimize_all：一键最小化所有可见窗口（不还原）。"""

    def _minimize_all(self):
        own_pid = os.getpid()
        count = 0

        def _callback(hwnd, _lparam):
            nonlocal count
            try:
                # 1) 排除本进程：桌宠 + 日程/天气/气泡等 Toplevel
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == own_pid:
                    return True
                # 2) 跳过不可见 / 已最小化 / cloaked(其它虚拟桌面)
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.IsIconic(hwnd):
                    return True
                if _is_cloaked(hwnd):
                    return True
                # 3) 跳过系统外壳窗口
                if _class_name(hwnd) in _SKIP_CLASSES:
                    return True
                # 4) 跳过无标题窗口（多为隐藏辅助窗）
                if user32.GetWindowTextLengthW(hwnd) == 0:
                    return True
                # 5) 跳过无任务栏按钮的悬浮工具窗（除非显式要求出现在任务栏）
                ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                if (ex_style & WS_EX_TOOLWINDOW) and not (
                        ex_style & WS_EX_APPWINDOW):
                    return True
                user32.ShowWindowAsync(hwnd, SW_MINIMIZE)
                count += 1
            except Exception:
                logger.exception('最小化单个窗口失败，已跳过')
            return True

        try:
            user32.EnumWindows(_ENUM_PROC(_callback), 0)
        except Exception:
            logger.exception('一键最小化失败')
            self._toast('最小化失败，请重试')
            return

        if count:
            self._toast(f'已最小化 {count} 个窗口')
        else:
            self._toast('没有可最小化的窗口')
