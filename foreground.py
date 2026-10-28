"""前台窗口检测：取当前最前面那个窗口所属进程的 exe 名。

用途：按应用统计敲键次数与停留时长时，需要知道「此刻用户正在哪个软件里」。

实现选择（重要）：
- 纯 ctypes 调 Win32 API，不新增 pywin32 / psutil 依赖。
- 先 GetForegroundWindow 拿 HWND，再拿 PID，最后 QueryFullProcessImageNameW
  取完整路径，basename 就是 exe 名（如 'chrome.exe'）。
- HWND → exe 的映射按窗口缓存：键盘监听每敲一下都要查一次，缓存后
  绝大多数按键只是命中字典，开销可忽略。

失败语义：任何一步失败都返回 None，调用方跳过这次统计即可，
绝不让检测失败影响键盘监听或主程序。
"""
import ctypes
import os
import sys
from ctypes import wintypes

# 非 Windows 平台（或在 CI 上跑测试）不导入 DLL，全部函数降级为返回 None。
_IS_WINDOWS = sys.platform.startswith('win')

_user32 = None
_kernel32 = None

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# 自身进程（桌宠窗口）的按键归属标记。
# 不叫 'python.exe' 是因为那会和用户真正用 Python 跑的东西混淆。
HOST_APP = '__host__'

if _IS_WINDOWS:
    try:
        _user32 = ctypes.WinDLL('user32', use_last_error=True)
        _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

        _user32.GetForegroundWindow.restype = wintypes.HWND
        _user32.GetForegroundWindow.argtypes = []

        _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        _user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
        ]

        _kernel32.OpenProcess.restype = wintypes.HANDLE
        _kernel32.OpenProcess.argtypes = [
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD,
        ]

        _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        _kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]

        _kernel32.CloseHandle.restype = wintypes.BOOL
        _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    except Exception:      # pragma: no cover - 仅在异常环境触发
        _user32 = None
        _kernel32 = None


def pid_to_exe(pid):
    """把进程 ID 转成 exe 文件名（如 'chrome.exe'）；失败返回 None。

    用 PROCESS_QUERY_LIMITED_INFORMATION 而非 PROCESS_QUERY_INFORMATION，
    这样对多数受保护进程也能拿到路径，且不需要管理员权限。
    """
    if not _kernel32 or not pid:
        return None
    handle = _kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        ok = _kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size))
        if not ok or not buf.value:
            return None
        return os.path.basename(buf.value)
    except Exception:
        return None
    finally:
        try:
            _kernel32.CloseHandle(handle)
        except Exception:
            pass


def foreground_window():
    """返回当前前台窗口的 HWND；拿不到返回 0。"""
    if not _user32:
        return 0
    try:
        return _user32.GetForegroundWindow() or 0
    except Exception:
        return 0


def window_pid(hwnd):
    """返回某个窗口所属进程的 PID；拿不到返回 0。"""
    if not _user32 or not hwnd:
        return 0
    try:
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value
    except Exception:
        return 0


class ForegroundSampler:
    """带缓存的「当前前台 exe」采样器。

    缓存 key 是 HWND：同一个窗口反复采样（打字时窗口不变）只是查字典。
    缓存上限做简单清理，避免长时间运行无限增长。

    自身进程不能返回 None——桌宠自己的窗口（日程表、琥珀）也会获得焦点，
    在里面打字时那些按键已经计入总数，如果这里丢掉就会造成
    「气泡 531 / 分布 517」这种对不上的情况。因此给自身进程一个明确标记，
    让统计能把它归到「桌宠」名下。
    """

    MAX_CACHE = 256

    def __init__(self, self_pid=None):
        self._cache = {}
        self._self_pid = self_pid if self_pid is not None else os.getpid()

    def current(self):
        """返回当前前台 exe 名；拿不到（权限/无窗口）时返回 None。"""
        hwnd = foreground_window()
        if not hwnd:
            return None

        cached = self._cache.get(hwnd)
        if cached is not None:
            return cached

        pid = window_pid(hwnd)
        if not pid:
            return None
        # 自身进程：明确归为「桌宠」，而不是丢弃
        if self._self_pid and pid == self._self_pid:
            return HOST_APP

        exe = pid_to_exe(pid)
        if exe:
            if len(self._cache) >= self.MAX_CACHE:
                self._cache.clear()
            self._cache[hwnd] = exe
        return exe

    def clear(self):
        """清空缓存（跨天或调试时用）。"""
        self._cache.clear()
