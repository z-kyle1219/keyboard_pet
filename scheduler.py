"""后台线程：负责 24:00 跨天刷新、周期性落库、天气定时播报。"""
import threading
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


# ============================================================
# 天气播报线程
# ============================================================
# 播报窗口：19:00 起，到 24:00 结束（主动弹卡片）
WEATHER_START_HOUR = 19
WEATHER_END_HOUR = 24
# 突变监控窗口：11:00 起（白天也监控，及早发现预报变化）
WEATHER_WATCH_START_HOUR = 11
# 窗口内检查间隔（秒）：1 小时
WEATHER_INTERVAL = 60 * 60
# 已确认后的突变检查间隔（秒）：1 小时
WEATHER_MUTATION_INTERVAL = 60 * 60


# 持久化键：写入 db 的 app_state 表，重启后恢复
_WEATHER_SHOWN_KEY = 'weather_last_shown'
_WEATHER_CONFIRMED_KEY = 'weather_confirmed'


class WeatherState:
    """天气播报的共享状态（线程安全 + 跨重启持久化）。

    两个日期字段（都按「当天」判定）：
    - shown_date：今天是否已弹过卡片（首播或突变都算）。
      持久化后，重启当次不再重复首播。
    - confirmed_date：用户当天点过「知道了」的日期；None 表示未确认。
    天气线程读 is_shown()/is_confirmed() 决定要不要播；
    界面线程点「知道了」时调 confirm() 写入。

    persist=False 时只存内存（单元测试用，避免碰真实数据库）。
    """

    def __init__(self, persist=True):
        self._lock = threading.Lock()
        self._persist = persist
        self.shown_date = None
        self.confirmed_date = None
        if persist:
            self._load()

    def _load(self):
        """启动时从 SQLite 恢复上次的已弹/已确认日期。"""
        try:
            from db import get_state
            self.shown_date = get_state(_WEATHER_SHOWN_KEY)
            self.confirmed_date = get_state(_WEATHER_CONFIRMED_KEY)
        except Exception:
            self.shown_date = None
            self.confirmed_date = None

    def _save(self, key, value):
        """持久化单个状态（失败只忽略，不拖垮程序）。"""
        if not self._persist:
            return
        try:
            from db import set_state
            set_state(key, value)
        except Exception:
            pass

    def confirm(self, date):
        """标记某天已确认。"""
        with self._lock:
            self.confirmed_date = date
        self._save(_WEATHER_CONFIRMED_KEY, date)

    def mark_shown(self, date):
        """标记某天已弹过卡片。"""
        with self._lock:
            self.shown_date = date
        self._save(_WEATHER_SHOWN_KEY, date)

    def is_confirmed(self, date):
        """某天是否已确认。"""
        with self._lock:
            return self.confirmed_date == date

    def is_shown(self, date):
        """某天是否已弹过卡片。"""
        with self._lock:
            return self.shown_date == date

    def reset_if_new_day(self, date):
        """跨天时清空当天状态（0 点重置，仅内存）。

        数据库里旧日期的值不必删除——is_shown/is_confirmed 用日期相等
        判断，旧值对新一天天然不匹配，不会误判。
        """
        with self._lock:
            if self.shown_date is not None and self.shown_date != date:
                self.shown_date = None
            if self.confirmed_date is not None and self.confirmed_date != date:
                self.confirmed_date = None


def _in_window(now):
    """是否在**播报**窗口内（19:00 <= now < 24:00）。"""
    return WEATHER_START_HOUR <= now.hour < WEATHER_END_HOUR


def _in_watch(now):
    """是否在**突变监控**窗口内（11:00 <= now < 24:00）。"""
    return WEATHER_WATCH_START_HOUR <= now.hour < WEATHER_END_HOUR


def weather_loop(show, state=None, interval=WEATHER_INTERVAL,
                 mutation_interval=WEATHER_MUTATION_INTERVAL,
                 sleep_fn=time.sleep, now_fn=datetime.now,
                 fetch_all=None, detect_change=None):
    """天气播报后台循环。

    参数注入（便于测试与解耦）：
    - show: 播报回调 show(current, changes)，由主程序传入（内部 root.after 回主线程）
    - state: 共享确认状态（WeatherState），默认内部新建
    - interval: 窗口内检查间隔秒数
    - mutation_interval: 已确认后的突变检查间隔秒数
    - sleep_fn / now_fn: 时间函数，测试时可替换
    - fetch_all / detect_change: 天气函数，默认用 weather 模块的

    逻辑（新模型：弹一次挂着 + 全天候突变监控）：
    1. 不在**监控窗口**（11–24）→ 只睡 60 秒轮询，不做任何请求
    2. 在监控窗口：
       - 未确认 且 当天还没弹过 且 已到播报时间（19 点）→ 拉一次并播报
       - 否则 → 每小时拉一次，检测突变（含预报变化），有变才弹
    每天 0 点重置「已确认」状态；第二天进入窗口时用新卡片替换旧的。
    """
    if state is None:
        state = WeatherState()
    # 延迟导入，避免模块级循环依赖
    if fetch_all is None or detect_change is None:
        import weather as weather_mod
        fetch_all = fetch_all or weather_mod.fetch_all
        detect_change = detect_change or weather_mod.detect_change

    last_weather = {}       # 上次天气快照，用于突变对比

    from logger import logger as _logger
    _logger.info('天气播报线程已启动（播报 %d:00，监控 %d:00-%d:00，间隔 %d 秒）',
                 WEATHER_START_HOUR, WEATHER_WATCH_START_HOUR,
                 WEATHER_END_HOUR, interval)

    while True:
        try:
            now = now_fn()
            today = now.strftime('%Y-%m-%d')
            state.reset_if_new_day(today)   # 0 点重置

            if not _in_watch(now):
                # 监控窗口外：睡 60 秒再看一次（避免长时间 sleep 导致跨天不准）
                sleep_fn(60)
                continue

            confirmed = state.is_confirmed(today)

            # 到播报时间（19 点）且未确认、当天未弹 → 拉一次并播报
            if (_in_window(now) and not confirmed
                    and not state.is_shown(today)):
                current = fetch_all()
                if current:
                    _logger.info('天气播报（首次）：%s', list(current.keys()))
                    show(current, [])
                    last_weather = current
                    state.mark_shown(today)
                sleep_fn(interval)
                continue

            # 其它情况（11–19 监控，或已确认/已弹）→ 每小时检查突变
            current = fetch_all()
            if current:
                changes = []
                for name, w in current.items():
                    ch = detect_change(last_weather.get(name), w)
                    if ch:
                        changes.append(f"{name}：{'、'.join(ch)}")
                if changes:
                    _logger.info('天气突变提醒：%s', changes)
                    show(current, changes)
                    state.mark_shown(today)
                last_weather = current
            sleep_fn(mutation_interval)
        except Exception:
            # 任何意外都记日志，绝不让天气线程静默死掉
            _logger.exception('天气播报循环异常（已忽略并继续）')
            sleep_fn(60)
