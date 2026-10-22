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
from pet_ui import PetApp
from scheduler import midnight_loop, periodic_save, weather_loop, WeatherState
from logger import logger


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
    manager = CountManager()
    key_listener = KeyListener(manager)
    key_listener.start()

    # 后台线程：跨天刷新 + 周期落库
    threading.Thread(target=midnight_loop, args=(manager,), daemon=True).start()
    threading.Thread(target=periodic_save, args=(manager,), daemon=True).start()

    root = tk.Tk()
    try:
        app = PetApp(root, manager)  # 持有引用，避免被 GC
    except Exception as e:
        # 界面初始化失败（如图标损坏、路径错误），记录日志而非崩溃
        logger.exception('桌宠界面初始化失败')
        key_listener.stop()
        manager.persist()
        root.destroy()
        sys.exit(1)

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
        manager.persist()  # 退出前把当前次数落库
        logger.info('程序已退出')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        logger.exception('程序发生未捕获异常，已终止')
        raise
