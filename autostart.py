"""开机自启动管理：通过当前用户的「启动」文件夹中的静默 VBS 启动器实现。

原理：把 KeyboardPet.vbs 写入「启动」文件夹，用 pythonw.exe（无控制台窗口）
静默启动 main.py；取消自启动则删除该 vbs。

相比注册表 Run 键，启动文件夹方案更直观、易排查，且同样在用户登录时自动运行。

设计要点：
- VBS 内容保持纯 ASCII（脚本宿主 WScript 默认按 ANSI/GBK 解释文件，
  UTF-8 中的中文注释会导致解析错误、静默崩溃），因此这里只用 ASCII。
- 每次启动会追加一行到 D:\\keyboard_pet\\startup.log，便于开机排查。
"""
import os
import sys

# 当前用户「启动」文件夹（Windows 标准路径）
STARTUP_DIR = os.path.join(
    os.environ['APPDATA'],
    'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup',
)
LAUNCHER_NAME = 'KeyboardPet.vbs'
LAUNCHER_PATH = os.path.join(STARTUP_DIR, LAUNCHER_NAME)

# 项目根目录（autostart.py 就在项目根下，取一级即可）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(PROJECT_ROOT, 'startup.log')


def _pythonw():
    """返回无窗口解释器路径：存在 pythonw 用 pythonw，否则用 python。"""
    python_dir = os.path.dirname(sys.executable)
    pythonw = os.path.join(python_dir, 'pythonw.exe')
    return pythonw if os.path.exists(pythonw) else sys.executable


def _launcher_content():
    """生成静默启动 VBS 的内容（纯 ASCII + 启动日志）。"""
    pythonw = _pythonw()
    main_py = os.path.join(PROJECT_ROOT, 'main.py')
    log_path = LOG_PATH
    cmd = '"{}" "{}"'.format(pythonw, main_py)
    lines = [
        "' KeyboardPet - silent boot launcher (ASCII only)",
        'Option Explicit',
        'Dim shell, fso, logPath, logFile',
        'Set shell = CreateObject("WScript.Shell")',
        'Set fso = CreateObject("Scripting.FileSystemObject")',
        "logPath = \"" + log_path + "\"",
        'On Error Resume Next',
        'Set logFile = fso.OpenTextFile(logPath, 8, True)',
        'If Err.Number = 0 Then',
        '    logFile.WriteLine Now & "  KeyboardPet VBS launcher executed"',
        '    logFile.Close',
        'End If',
        'On Error GoTo 0',
        'shell.Run "' + cmd + '", 0, False',
        'Set shell = Nothing',
        'Set fso = Nothing',
    ]
    return '\r\n'.join(lines) + '\r\n'


def is_enabled():
    """查询是否已启用开机自启动。"""
    return os.path.exists(LAUNCHER_PATH)


def enable():
    """启用开机自启动：写入静默启动 VBS。"""
    try:
        os.makedirs(STARTUP_DIR, exist_ok=True)
        with open(LAUNCHER_PATH, 'w', encoding='ascii', newline='') as f:
            f.write(_launcher_content())
    except Exception:
        return False
    return True


def disable():
    """取消开机自启动：删除启动 VBS。"""
    try:
        if os.path.exists(LAUNCHER_PATH):
            os.remove(LAUNCHER_PATH)
    except Exception:
        pass
    return True


def toggle():
    """切换状态，返回切换后是否开启。"""
    if is_enabled():
        disable()
        return False
    enable()
    return True
