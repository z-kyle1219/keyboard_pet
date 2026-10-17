"""计数核心：线程安全的当天计数 + 按键明细 + 跨天滚动。

统计口径（已定稿）：仅键盘，任意键按下 +1，修饰键也算，鼠标不计。
"""
import threading
from datetime import datetime

import db
from logger import logger


def key_to_name(key):
    """把 pynput 的 key 归一化成可入库/展示的字符串。

    - 普通字符键：key.char，如 'a'、'1'
    - 功能/特殊键：key.name，如 'space'、'enter'、'shift'
    - 取不到时回退到 str(key) 再清理，保证不至于崩溃
    """
    try:
        if hasattr(key, 'char') and key.char is not None:
            return key.char
        if hasattr(key, 'name') and key.name:
            return key.name
    except Exception:
        pass
    try:
        return str(key).replace('Key.', '').strip()
    except Exception:
        return 'unknown'


class CountManager:
    """管理"今天已敲键次数"与"各键次数"，并在跨天时归档到数据库。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._today = datetime.now().strftime('%Y-%m-%d')
        # 若当天重启程序，从数据库恢复已记录次数，避免清零
        self._count = db.get_count(self._today)
        self._key_counts = db.get_key_counts(self._today)
        # 订阅者：每次按键时收到 (key_name)，供热力图等实时响应。
        self._listeners = []

    def add_listener(self, fn):
        """注册一个按键回调 fn(key_name)。

        回调在监听线程内同步执行，因此应轻量、不阻塞、不吐异常
        （异常会被捕获并记日志）。
        """
        with self._lock:
            self._listeners.append(fn)

    def remove_listener(self, fn):
        """移除一个按键回调（热力图窗口关闭时调用）。"""
        with self._lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def _notify(self, key_name):
        """在锁外通知所有订阅者（避免持有锁时回调产生死锁/重入）。"""
        for fn in list(self._listeners):
            try:
                fn(key_name)
            except Exception:
                logger.exception('按键回调异常')

    def increment(self, key=None):
        """键盘按下时 +1（监听线程调用），并累计该键的次数。

        长按一个键时 pynput 会自动重复触发 on_press，每次触发都会 +1，
        与单击效果一致（均计入）。
        在 +1 前先做跨天前置检查：若日期已变，归档旧的一天再计数，
        避免依赖 midnight_loop 线程可能因休眠/挂起而漏滚动。
        """
        notified_key = None
        with self._lock:
            now = datetime.now().strftime('%Y-%m-%d')
            if now != self._today:
                # 跨天：先归档旧的一天，再开启新的一天
                try:
                    db.save_count(self._today, self._count)
                    db.save_key_counts(self._today, self._key_counts)
                    self._today = now
                    self._count = db.get_count(now)
                    self._key_counts = db.get_key_counts(now)
                except Exception:
                    # 跨天归档失败也继续 +1，避免丢失本次按键
                    logger.exception('跨天归档失败')
                    self._today = now
                    self._count = 0
                    self._key_counts = {}
            self._count += 1
            if key is not None:
                name = key_to_name(key)
                self._key_counts[name] = self._key_counts.get(name, 0) + 1
                notified_key = name

        # 锁外通知订阅者（避免持有锁时回调导致重入/死锁）
        if notified_key is not None:
            self._notify(notified_key)

    def snapshot(self):
        """把当前计数与各键计数落库，并返回这同一时刻的计数（供界面一次性使用）。

        在同一个锁内完成「写库 + 取值」，保证返回值与数据库里「今天」
        那一行完全一致，从根源上消除表头实时值与表格快照之间的竞态偏差。
        """
        with self._lock:
            try:
                db.save_count(self._today, self._count)
                db.save_key_counts(self._today, self._key_counts)
            except Exception:
                logger.exception('快照落库失败')
            return self._count

    def snapshot_keys(self):
        """返回当前各键计数的副本（供热力图一次性读取，不落库）。"""
        with self._lock:
            return dict(self._key_counts)

    def current_count(self):
        with self._lock:
            return self._count

    def today_str(self):
        with self._lock:
            return self._today

    def persist(self):
        """把当前累计次数与各键次数落库（周期调用，防崩溃丢数据）。"""
        with self._lock:
            try:
                db.save_count(self._today, self._count)
                db.save_key_counts(self._today, self._key_counts)
            except Exception:
                # 写库失败不要拖垮程序，记录日志即可
                logger.exception('落库失败')

    def rollover(self):
        """跨天刷新：归档旧的一天，开启新的一天。"""
        with self._lock:
            now = datetime.now().strftime('%Y-%m-%d')
            if now != self._today:
                db.save_count(self._today, self._count)
                db.save_key_counts(self._today, self._key_counts)
                self._today = now
                self._count = db.get_count(now)
                self._key_counts = db.get_key_counts(now)
