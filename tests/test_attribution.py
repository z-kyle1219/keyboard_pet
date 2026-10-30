"""归属对账：气泡里的「总次数」必须等于分布窗口里各应用之和。

历史上这两个数字对不上（气泡 531 / 分布 517），根因有两个：

- 前台采样失败时，那次按键被直接丢掉了；
- 重启后只恢复明细，没有和 daily_stats 里的总数对账。

这两个用例把「每次按键都有归属」和「重启后仍然对得上」钉住。
"""
import pytest

import app_usage
import db
import tracker


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """把 db 层的库指向临时文件，保证测试隔离。"""
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'attribution_test.db'))
    return db


class FakeSampler:
    """可随时切换当前前台 exe 的采样器；exe=None 表示采样失败。"""

    def __init__(self, exe='code.exe'):
        self.exe = exe

    def current(self):
        return self.exe


class FakeKey:
    def __init__(self, char):
        self.char = char
        self.name = None


def _press(manager, app_tracker, char='a'):
    """按一次键：严格按 listener._on_press 的顺序驱动两条统计链。"""
    manager.increment(FakeKey(char))
    app_tracker.record_key()


def test_unattributed_keeps_total_in_sync(temp_db):
    """采样失败的按键归到「未识别」，不许丢。"""
    day = '2026-10-27'
    manager = tracker.CountManager(now_fn=lambda: day)
    sampler = FakeSampler('code.exe')
    app_tracker = app_usage.AppUsageTracker(
        sampler=sampler, persist=False, now_fn=lambda: day)

    _press(manager, app_tracker)
    _press(manager, app_tracker)
    sampler.exe = None                # 前台窗口取不到
    _press(manager, app_tracker)

    data = app_tracker.today()
    assert manager.current_count() == 3
    assert app_tracker.today_total() == 3
    assert data['code.exe']['count'] == 2
    assert data[app_usage.UNATTRIBUTED]['count'] == 1


def test_restart_keeps_total_in_sync(temp_db):
    """库里总数 20、明细只有 15：重启后差额记「未识别」，两个数字相等。"""
    day = '2026-10-27'
    temp_db.save_count(day, 20)
    temp_db.save_app_stats(day, {'code.exe': 15})

    manager = tracker.CountManager(now_fn=lambda: day)
    app_tracker = app_usage.AppUsageTracker(
        sampler=FakeSampler('code.exe'), persist=True, now_fn=lambda: day)

    assert manager.current_count() == 20
    assert app_tracker.today_total() == 20
    assert app_tracker.today()[app_usage.UNATTRIBUTED]['count'] == 5


def test_rollover_keeps_both_sides_in_sync(temp_db):
    """跨天后：昨天的总次数 == 昨天各应用之和；今天两边也都相等。"""
    clock = {'day': '2026-10-27'}
    manager = tracker.CountManager(now_fn=lambda: clock['day'])
    sampler = FakeSampler('code.exe')
    app_tracker = app_usage.AppUsageTracker(
        sampler=sampler, persist=True, now_fn=lambda: clock['day'])

    _press(manager, app_tracker)
    _press(manager, app_tracker)
    manager.persist()
    app_tracker.persist()

    clock['day'] = '2026-10-28'
    _press(manager, app_tracker)

    assert temp_db.get_count('2026-10-27') == 2
    assert temp_db.get_app_total('2026-10-27') == 2
    assert manager.current_count() == 1
    assert app_tracker.today_total() == 1
