"""按应用统计：敲键次数 + 前台停留秒数 + 跨天归档。

两个正交指标（这是本模块存在的理由）：
- count   在该应用里敲了多少键 —— 打字强度
- seconds 该应用作为前台窗口待了多久 —— 占用强度

只看 count 会误判：在浏览器里看两小时网页，敲键可能只有几十次。
两个指标合起来才能回答「今天真正花时间在哪」。

线程模型：
- record_key() 由键盘监听线程调用（每次按键一次），只做纯内存累加；
- tick() 由本模块自己的后台线程每秒调用一次，采样前台窗口，累加秒数；
- persist() 由 scheduler 的周期任务调用，把内存值写进 daily_app_stats。
三者共用同一把锁，跨天检查在每次写内存前先做。
"""
import threading
import time
from datetime import datetime

import db
from foreground import ForegroundSampler
from logger import logger

# 单次采样最多累计的秒数：防止睡眠/休眠后 time.monotonic 大跳变，
# 把一觉睡 8 小时全部算到某个应用头上。
MAX_TICK_DELTA = 3.0

# 采样失败的按键归属桶。
# 以前这里直接 return False 把这次按键丢掉，导致「总次数」比
# 「各应用明细之和」多出一截（气泡 531 / 分布 517）。
# 现在宁可记成「未识别」，也不让两个数字脱节。
UNATTRIBUTED = '__unattributed__'

# 这些进程在前台时不算「使用时长」。
# 锁屏意味着人已离开，把它计入前台时长会让「今天用了多久」虚高。
# 注意：按键仍然照常计数（归到对应的应用名），只是不计时——
# 否则总数与明细又会脱节。
# 不同 Windows 版本锁屏相关的进程名不完全一样，所以列了几种。
IDLE_EXES = {
    'lockapp.exe',          # Win10/11 锁屏界面
    'logonui.exe',          # 登录 / 锁屏宿主
    'windowssecurity.exe',  # 安全选项界面
}


def _today_str():
    return datetime.now().strftime('%Y-%m-%d')


class AppUsageTracker:
    """当天各应用的敲键次数与停留秒数（线程安全 + 跨天归档）。"""

    TICK_SECONDS = 1.0

    def __init__(self, sampler=None, persist=True, now_fn=None):
        self._lock = threading.Lock()
        self._persist_enabled = persist
        self._now = now_fn or _today_str
        self._sampler = sampler or ForegroundSampler()
        self._today = self._now()
        self._counts = {}      # exe -> int
        self._seconds = {}     # exe -> float（内存用浮点累加，落库取整）
        self._last_exe = None
        self._last_ts = None
        self._thread = None
        if persist:
            # 先把历史数据里的锁屏时长抹平：只改未来采样挡不住旧值，
            # 否则重启后从库里恢复，锁屏时长又会冒出来
            self._scrub_idle_seconds()
            self._restore(self._today)

    # ---------- 内部 ----------
    def _scrub_idle_seconds(self):
        """把库里锁屏类进程的秒数清零（次数保留，保证总数对得上）。"""
        try:
            db.clear_idle_seconds(IDLE_EXES)
        except Exception:
            logger.exception('清理历史锁屏时长失败')
    def _restore(self, date_str):
        """从数据库恢复某天的数据（重启后不清零）。

        persist=False 时（单元测试）不碰数据库，直接置空。

        恢复完后会与 daily_stats 的总数对一次账：若总数比明细之和多，
        差额记为「未识别」。这样老数据遗留的缺口也能对上，不会让
        两个数字在重启之后继续各说各话。
        """
        if not self._persist_enabled:
            self._counts = {}
            self._seconds = {}
            return
        try:
            rows = db.get_app_stats(date_str)
        except Exception:
            logger.exception('应用统计恢复失败')
            rows = {}
        self._counts = {a: v['count'] for a, v in rows.items()}
        self._seconds = {a: float(v['seconds']) for a, v in rows.items()}

        try:
            total = db.get_count(date_str)
        except Exception:
            total = 0
        counted = sum(int(c) for c in self._counts.values())
        if total > counted:
            gap = total - counted
            self._counts[UNATTRIBUTED] = (
                self._counts.get(UNATTRIBUTED, 0) + gap)

    def _persist_locked(self):
        """调用方必须已持有锁。写库失败只记日志，不拖垮程序。"""
        if not self._persist_enabled:
            return
        try:
            counts = {a: int(c) for a, c in self._counts.items()}
            seconds = {a: int(round(s)) for a, s in self._seconds.items()}
            db.save_app_stats(self._today, counts, seconds)
        except Exception:
            logger.exception('应用统计落库失败')

    def _rollover_locked(self):
        """跨天：先归档旧的一天，再切到新的一天。调用方必须已持有锁。"""
        now = self._now()
        if now == self._today:
            return
        self._persist_locked()
        self._today = now
        self._restore(now)
        # 新一天的时长从零开始累积，不继承上一刻的采样点
        self._last_exe = None
        self._last_ts = None

    # ---------- 对外 ----------
    def record_key(self, exe=None):
        """记录一次按键归属的应用（监听线程调用）。

        exe 传 None 时内部自行采样前台窗口。采样失败不丢弃，记入
        UNATTRIBUTED——统计口径是「每次按键都要有归属」，否则
        总数与明细会越拉越开。
        """
        if exe is None:
            try:
                exe = self._sampler.current()
            except Exception:
                logger.exception('前台应用采样失败')
                exe = None
        if not exe:
            exe = UNATTRIBUTED
        with self._lock:
            self._rollover_locked()
            self._counts[exe] = self._counts.get(exe, 0) + 1
        return True

    def tick(self):
        """采样一次前台窗口，把流逝的时间累加到「上一个」应用头上。"""
        try:
            exe = self._sampler.current()
        except Exception:
            logger.exception('前台应用采样失败')
            return
        # 锁屏时人不在电脑前，不计入使用时长
        if exe and exe.lower() in IDLE_EXES:
            exe = None
        now = time.monotonic()
        with self._lock:
            # 先跨天检查：新的一天要清空采样点，重新开始累计
            self._rollover_locked()
            if self._last_ts is None:
                self._last_ts = now
                self._last_exe = exe
                return
            delta = now - self._last_ts
            if delta < 0 or delta > MAX_TICK_DELTA:
                delta = 0.0
            self._last_ts = now
            prev = self._last_exe
            self._last_exe = exe
            if not prev or delta <= 0:
                return
            self._seconds[prev] = self._seconds.get(prev, 0.0) + delta

    def start(self):
        """启动后台采样线程（每秒一次，daemon）。"""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name='app-usage', daemon=True)
        self._thread.start()

    def _loop(self):
        while True:
            try:
                self.tick()
            except Exception:
                logger.exception('应用时长采样异常')
            time.sleep(self.TICK_SECONDS)

    def persist(self):
        """把当前数据落库（周期调用，防崩溃丢数据）。"""
        with self._lock:
            self._persist_locked()

    def rollover(self):
        """跨天刷新（midnight_loop 调用；tick/record_key 里也有前置检查）。"""
        with self._lock:
            self._rollover_locked()

    def today(self):
        """返回今天的应用统计副本：{exe: {'count': int, 'seconds': int}}。

        次数和秒数都为 0 的条目不返回——锁屏清零后如果没有按键，
        它只会是一个空壳，没必要占列表位置。
        """
        with self._lock:
            apps = set(self._counts) | set(self._seconds)
            out = {}
            for a in apps:
                c = int(self._counts.get(a, 0))
                s = int(round(self._seconds.get(a, 0.0)))
                if c or s:
                    out[a] = {'count': c, 'seconds': s}
            return out

    def today_total(self):
        """今天所有应用敲键次数之和（含尚未落库的实时值）。"""
        with self._lock:
            return sum(int(c) for c in self._counts.values())
