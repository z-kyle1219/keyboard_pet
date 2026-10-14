"""计数核心：线程安全的当天计数 + 跨天滚动。

统计口径（已定稿）：仅键盘，任意键按下 +1，修饰键也算，鼠标不计。
"""
import threading
from datetime import datetime

import db
from logger import logger


class CountManager:
    """管理"今天已敲键次数"，并在跨天时归档到数据库。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._today = datetime.now().strftime('%Y-%m-%d')
        # 若当天重启程序，从数据库恢复已记录次数，避免清零
        self._count = db.get_count(self._today)

    def increment(self):
        """键盘按下时 +1（监听线程调用）。

        长按一个键时 pynput 会自动重复触发 on_press，每次触发都会 +1，
        与单击效果一致（均计入）。
        在 +1 前先做跨天前置检查：若日期已变，归档旧的一天再计数，
        避免依赖 midnight_loop 线程可能因休眠/挂起而漏滚动。
        """
        with self._lock:
            now = datetime.now().strftime('%Y-%m-%d')
            if now != self._today:
                # 跨天：先归档旧的一天，再开启新的一天
                try:
                    db.save_count(self._today, self._count)
                    self._today = now
                    self._count = db.get_count(now)
                except Exception:
                    # 跨天归档失败也继续 +1，避免丢失本次按键
                    logger.exception('跨天归档失败')
                    self._today = now
                    self._count = 0
            self._count += 1

    def snapshot(self):
        """把当前计数落库，并返回这同一时刻的计数（供界面一次性使用）。

        在同一个锁内完成「写库 + 取值」，保证返回值与数据库里「今天」
        那一行完全一致，从根源上消除表头实时值与表格快照之间的竞态偏差。
        """
        with self._lock:
            try:
                db.save_count(self._today, self._count)
            except Exception:
                logger.exception('快照落库失败')
            return self._count

    def current_count(self):
        with self._lock:
            return self._count

    def today_str(self):
        with self._lock:
            return self._today

    def persist(self):
        """把当前累计次数落库（周期调用，防崩溃丢数据）。"""
        with self._lock:
            try:
                db.save_count(self._today, self._count)
            except Exception:
                # 写库失败不要拖垮程序，记录日志即可
                logger.exception('落库失败')

    def rollover(self):
        """跨天刷新：归档旧的一天，开启新的一天。"""
        with self._lock:
            now = datetime.now().strftime('%Y-%m-%d')
            if now != self._today:
                db.save_count(self._today, self._count)
                self._today = now
                self._count = db.get_count(now)
