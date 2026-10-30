"""跨天滚动的回归测试：不依赖 midnight_loop 线程，也不依赖真实时钟。

CountManager 接收注入的 now_fn 后，可以把日期「拨」到次日，
在毫秒内验证三条路径：

1. 每次 +1 前的跨天前置检查（休眠/挂起导致定时线程漏触发时的兜底）
2. 旧的一天被归档，新的一天接着库里的值继续数
3. 归档失败时仍然不丢这一次按键

全部通过 monkeypatch 把 db.DB_PATH 指向临时文件，绝不碰真实库。
"""
import pytest

import db
import tracker


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """把 db 层的库指向临时文件，保证测试隔离。"""
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'tracker_test.db'))
    return db


class FakeKey:
    """最小化的 pynput 按键替身：只需要 char / name 两个属性。"""

    def __init__(self, char):
        self.char = char
        self.name = None


def _manager(clock):
    """clock 是可变字典：改 clock['day'] 等于把系统日期拨到另一天。"""
    return tracker.CountManager(now_fn=lambda: clock['day'])


def test_counts_accumulate_within_same_day(temp_db):
    clock = {'day': '2026-10-27'}
    manager = _manager(clock)

    manager.increment(FakeKey('a'))
    manager.increment(FakeKey('b'))
    manager.increment()          # 不传 key：只计总数，不计按键明细

    assert manager.current_count() == 3
    assert manager.snapshot_keys() == {'a': 1, 'b': 1}
    assert manager.today_str() == '2026-10-27'


def test_increment_rolls_over_without_midnight_thread(temp_db):
    """核心用例：不调用 rollover()，只靠 increment 的前置检查跨天。"""
    clock = {'day': '2026-10-27'}
    manager = _manager(clock)
    for _ in range(3):
        manager.increment(FakeKey('e'))

    # 电脑睡了一夜醒来，midnight_loop 根本没跑到，直接按下了第一个键
    clock['day'] = '2026-10-28'
    manager.increment(FakeKey('a'))

    assert manager.today_str() == '2026-10-28'
    assert manager.current_count() == 1        # 昨天的次数没滚进今天
    assert manager.snapshot_keys() == {'a': 1}
    # 昨天已归档，而且是按「键」粒度归档的
    assert temp_db.get_count('2026-10-27') == 3
    assert temp_db.get_key_counts('2026-10-27') == {'e': 3}


def test_new_day_resumes_from_existing_db_value(temp_db):
    """跨天时若新的一天库里已有记录（上次运行留下的），要接着数而不是清零。"""
    temp_db.save_count('2026-10-28', 5)

    clock = {'day': '2026-10-27'}
    manager = _manager(clock)
    manager.increment()
    manager.increment()

    clock['day'] = '2026-10-28'
    manager.increment()

    assert manager.current_count() == 6


def test_rollover_is_idempotent(temp_db):
    """同一天里多次调用 rollover 不改变计数，也不重复归档。"""
    clock = {'day': '2026-10-27'}
    manager = _manager(clock)
    manager.increment()
    manager.persist()

    manager.rollover()
    manager.rollover()

    assert manager.current_count() == 1
    assert temp_db.get_count('2026-10-27') == 1


def test_restart_recovers_same_day_counts(temp_db):
    """当天重启：总次数与按键明细都从库里恢复，不清零。"""
    clock = {'day': '2026-10-27'}
    first = _manager(clock)
    first.increment(FakeKey('e'))
    first.increment(FakeKey('e'))
    first.persist()

    second = _manager(clock)          # 模拟重启

    assert second.current_count() == 2
    assert second.snapshot_keys() == {'e': 2}


def test_archive_failure_does_not_drop_current_key(temp_db, monkeypatch):
    """归档失败（磁盘满/库被占用）时，仍然把这一次按键算进去。"""
    clock = {'day': '2026-10-27'}
    manager = _manager(clock)
    manager.increment()

    def boom(*args, **kwargs):
        raise RuntimeError('disk full')

    monkeypatch.setattr(db, 'save_count', boom)

    clock['day'] = '2026-10-28'
    manager.increment()               # 不应抛异常

    assert manager.today_str() == '2026-10-28'
    assert manager.current_count() == 1
