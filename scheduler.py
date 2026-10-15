"""后台线程：负责 24:00 跨天刷新与周期性落库。"""
import time
from datetime import datetime, timedelta


def midnight_loop(manager):
    """一直等到下一个 00:00:00，然后触发跨天滚动。"""
    while True:
        now = datetime.now()
        next_midnight = (now.replace(hour=0, minute=0, second=0, microsecond=0)
                         + timedelta(days=1))
        # +0.5 秒确保跨过整点（避免边界抖动）
        time.sleep((next_midnight - now).total_seconds() + 0.5)
        manager.rollover()


def periodic_save(manager):
    """每 20 秒把当前次数与各键次数落库一次，防止意外退出丢数据。

    间隔缩短到 20 秒：关机/强杀最多丢最后 20 秒，降低数据丢失窗口。
    """
    while True:
        time.sleep(20)
        manager.persist()
