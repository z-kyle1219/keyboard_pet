"""全局键盘监听：用 pynput 捕获任意按键，不回传、不拦截。"""
from pynput import keyboard

from logger import logger


class KeyListener:
    def __init__(self, manager, app_tracker=None):
        self.manager = manager
        # 按应用统计（可为 None：不需要时报掉即可，不影响主计数）
        self.app_tracker = app_tracker
        # on_press 在每个键按下时触发，含修饰键；不调用 suppress 所以不影响打字
        self._listener = keyboard.Listener(on_press=self._on_press)

    def _on_press(self, key):
        # 计数异常时记录日志，但绝不影响后续键盘监听
        try:
            self.manager.increment(key)
        except Exception:
            logger.exception('按键计数异常')
        # 按应用计数独立 try：一边出错不拖垮另一边
        if self.app_tracker is not None:
            try:
                self.app_tracker.record_key()
            except Exception:
                logger.exception('按应用计数异常')

    def start(self):
        self._listener.start()

    def stop(self):
        self._listener.stop()
