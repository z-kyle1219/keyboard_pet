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
# 播报窗口：19:00 起，到 24:00 结束
WEATHER_START_HOUR = 19
WEATHER_END_HOUR = 24
# 窗口内检查间隔（秒）：10 分钟（用于 B2 突变兜底，不再重复弹播报）
WEATHER_INTERVAL = 10 * 60
# 已确认后的突变检查间隔（秒）：1 小时
WEATHER_MUTATION_INTERVAL = 60 * 60


class WeatherState:
    """天气播报的共享状态（线程安全）。

    confirmed_date：用户当天点过「知道了」的日期；None 表示未确认。
    - 天气线程读 is_confirmed() 决定要不要再播
    - 界面线程点「知道了」时调 confirm() 写入
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.confirmed_date = None

    def confirm(self, date):
        """标记某天已确认。"""
        with self._lock:
            self.confirmed_date = date

    def is_confirmed(self, date):
        """某天是否已确认。"""
        with self._lock:
            return self.confirmed_date == date

    def reset_if_new_day(self, date):
        """跨天时清空确认状态（0 点重置）。"""
        with self._lock:
            if self.confirmed_date is not None and self.confirmed_date != date:
                self.confirmed_date = None


def _in_window(now):
    """判断当前时间是否在播报窗口内（19:00 <= now < 24:00）。"""
    return WEATHER_START_HOUR <= now.hour < WEATHER_END_HOUR


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

    逻辑（新模型：弹一次挂着 + B2 突变兜底）：
    1. 不在窗口内 → 只睡 60 秒轮询，不做任何请求
    2. 进入窗口且未确认 → 拉一次天气并播报（卡片会挂着，不自动消失）
    3. 已确认后 → 不再重复播报，但每 mutation_interval 拉一次：
       - 检测到突变 → 再播报一次（兜底）
       - 无突变 → 静默
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
    shown_date = None       # 当天是否已弹过卡片（弹一次就挂着，不重复弹）

    from logger import logger as _logger
    _logger.info('天气播报线程已启动（窗口 %d:00-%d:00，检查 %d 秒，突变 %d 秒）',
                 WEATHER_START_HOUR, WEATHER_END_HOUR, interval,
                 mutation_interval)

    while True:
        try:
            now = now_fn()
            today = now.strftime('%Y-%m-%d')
            state.reset_if_new_day(today)   # 0 点重置

            if not _in_window(now):
                # 窗口外：睡 60 秒再看一次（避免长时间 sleep 导致跨天不准）
                sleep_fn(60)
                continue

            # 跨天：清空当天已弹标记（第二天用新卡片替换旧的）
            if shown_date is not None and shown_date != today:
                shown_date = None

            confirmed = state.is_confirmed(today)

            # 未确认 且 当天还没弹过 → 拉一次并播报（卡片挂着，不自动消失）
            if not confirmed and shown_date != today:
                current = fetch_all()
                if current:
                    _logger.info('天气播报（首次）：%s', list(current.keys()))
                    show(current, [])
                    last_weather = current
                    shown_date = today
                sleep_fn(interval)
                continue

            # 已确认 或 当天已弹过 → 低频检查突变（B2 兜底）
            current = fetch_all()
            if current:
                changes = []
                for name, w in current.items():
                    ch = detect_change(last_weather.get(name), w)
                    if ch:
                        changes.append(f"{name}：{'、'.join(ch)}")
                if changes:
                    _logger.info('天气突变兜底播报：%s', changes)
                    show(current, changes)
                    shown_date = today
                last_weather = current
            sleep_fn(mutation_interval)
        except Exception:
            # 任何意外都记日志，绝不让天气线程静默死掉
            _logger.exception('天气播报循环异常（已忽略并继续）')
            sleep_fn(60)
