"""全局键盘监听：用 pynput 捕获任意按键，不回传、不拦截。"""
from pynput import keyboard

from logger import logger


class KeyListener:
    def __init__(self, manager):
        self.manager = manager
        # on_press 在每个键按下时触发，含修饰键；不调用 suppress 所以不影响打字
        self._listener = keyboard.Listener(on_press=self._on_press)

    def _on_press(self, key):
        # 计数异常时记录日志，但绝不影响后续键盘监听
        try:
            self.manager.increment(key)
        except Exception:
            logger.exception('按键计数异常')

    def start(self):
        self._listener.start()

    def stop(self):
        self._listener.stop()
