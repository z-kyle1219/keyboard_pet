"""程序入口：启动键盘监听 + 桌宠窗口 + 后台线程。

健壮性设计：
- 用 try/except 包围关键流程，任意异常都写日志，避免程序无声消失。
- 图标加载失败等不致命问题，记录日志后仍尝试继续运行。
"""
import ctypes
import sys
import threading
import tkinter as tk

from tracker import CountManager
from listener import KeyListener
from app_usage import AppUsageTracker
from pet_ui import PetApp
from scheduler import midnight_loop, periodic_save, weather_loop, WeatherState
from logger import logger
import stats_export


def _enable_dpi_awareness():
    """开启 DPI 感知，避免 tkinter 在高分屏下文字模糊（像素块）。

    必须在创建 Tk 窗口之前调用。优先用 Windows 10+ 的 per-monitor 感知。
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    _enable_dpi_awareness()
    # 首次运行时生成一份可编辑的 exe 别名表（已存在则不覆盖）
    try:
        from app_aliases import write_default_file
        write_default_file()
    except Exception:
        logger.exception('初始化 app_aliases.json 失败（不影响主流程）')

    manager = CountManager()
    # 按应用统计：敲键归属哪个 exe + 前台停留秒数
    app_tracker = AppUsageTracker()
    app_tracker.start()
    key_listener = KeyListener(manager, app_tracker)
    key_listener.start()

    # 后台线程：跨天刷新 + 周期落库（含应用统计与 JSON 导出）
    threading.Thread(target=midnight_loop, args=(manager, app_tracker),
                     daemon=True).start()
    threading.Thread(target=periodic_save, args=(manager, app_tracker),
                     daemon=True).start()

    root = tk.Tk()
    try:
        app = PetApp(root, manager, app_tracker)  # 持有引用，避免被 GC
    except Exception as e:
        # 界面初始化失败（如图标损坏、路径错误），记录日志而非崩溃
        logger.exception('桌宠界面初始化失败')
        key_listener.stop()
        manager.persist()
        app_tracker.persist()
        root.destroy()
        sys.exit(1)

    # 全局热键：Ctrl+Alt+T 直译剪贴板（失败只记日志，不影响主流程）
    try:
        app.start_translate_hotkey()
    except Exception:
        logger.exception('翻译热键启动失败（不影响主流程）')

    # 后台线程：天气播报
    # show 在天气线程里被调用，必须用 root.after 甩回主线程再碰界面
    weather_state = WeatherState()
    app._weather_state = weather_state

    def _show_weather(current, changes):
        root.after(0, lambda: app.show_weather(current, changes))

    threading.Thread(
        target=weather_loop,
        args=(_show_weather, weather_state),
        daemon=True,
    ).start()

    try:
        root.mainloop()
    except Exception as e:
        logger.exception('主循环运行异常')
    finally:
        key_listener.stop()
        try:
            app.stop_translate_hotkey()
        except Exception:
            pass
        manager.persist()  # 退出前把当前次数落库
        app_tracker.persist()
        try:
            stats_export.write_json(live_today=app_tracker.today())
        except Exception:
            pass
        logger.info('程序已退出')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        logger.exception('程序发生未捕获异常，已终止')
        raise
