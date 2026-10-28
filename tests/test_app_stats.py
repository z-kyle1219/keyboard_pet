"""按应用统计的单元测试：db 层、别名解析、tracker、JSON 导出。

运行：uv run pytest

全部通过 monkeypatch 把 db.DB_PATH 指向临时文件，绝不碰真实库。
"""
import pytest

import app_aliases
import app_usage
import db
import stats_export


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """把 db 层的库指向临时文件，保证测试隔离。"""
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'app_stats_test.db'))
    return db


# ---------- db 层 ----------
def test_save_and_get_app_stats(temp_db):
    temp_db.save_app_stats('2026-10-27', {'code.exe': 120, 'chrome.exe': 80},
                           {'code.exe': 3600, 'chrome.exe': 7200})
    rows = temp_db.get_app_stats('2026-10-27')
    assert rows['code.exe'] == {'count': 120, 'seconds': 3600}
    assert rows['chrome.exe'] == {'count': 80, 'seconds': 7200}


def test_upsert_overwrites_same_day(temp_db):
    temp_db.save_app_stats('2026-10-27', {'code.exe': 10})
    temp_db.save_app_stats('2026-10-27', {'code.exe': 25})
    assert temp_db.get_app_stats('2026-10-27')['code.exe']['count'] == 25


def test_only_seconds_app_is_saved(temp_db):
    """只看不敲的应用也要留下记录（seconds 维度独立）。"""
    temp_db.save_app_stats('2026-10-27', {}, {'chrome.exe': 1800})
    rows = temp_db.get_app_stats('2026-10-27')
    assert rows['chrome.exe'] == {'count': 0, 'seconds': 1800}


def test_aggregate_sums_across_days(temp_db):
    temp_db.save_app_stats('2026-10-25', {'chrome.exe': 100}, {'chrome.exe': 600})
    temp_db.save_app_stats('2026-10-26', {'chrome.exe': 200}, {'chrome.exe': 900})
    temp_db.save_app_stats('2026-10-27', {'chrome.exe': 50, 'code.exe': 300},
                           {'chrome.exe': 300, 'code.exe': 1200})

    rows = dict((a, (c, s)) for a, c, s in
                temp_db.get_app_aggregate('2026-10-25'))
    assert rows['chrome.exe'] == (350, 1800)
    assert rows['code.exe'] == (300, 1200)


def test_aggregate_respects_window(temp_db):
    """区间外的日期不参与聚合。"""
    temp_db.save_app_stats('2026-10-20', {'chrome.exe': 999})
    temp_db.save_app_stats('2026-10-27', {'chrome.exe': 10})
    rows = temp_db.get_app_aggregate('2026-10-25')
    assert rows == [('chrome.exe', 10, 0)]


def test_aggregate_order_by_seconds(temp_db):
    temp_db.save_app_stats('2026-10-27', {'code.exe': 500, 'chrome.exe': 100},
                           {'code.exe': 600, 'chrome.exe': 7200})
    by_count = temp_db.get_app_aggregate('2026-10-27', order_by='count')
    by_time = temp_db.get_app_aggregate('2026-10-27', order_by='seconds')
    assert by_count[0][0] == 'code.exe'
    assert by_time[0][0] == 'chrome.exe'


def test_get_app_daily_returns_pairs(temp_db):
    temp_db.save_app_stats('2026-10-26', {'code.exe': 10}, {'code.exe': 60})
    daily = temp_db.get_app_daily('2026-10-26', '2026-10-27')
    assert daily[('code.exe', '2026-10-26')] == (10, 60)


def test_get_app_total(temp_db):
    temp_db.save_app_stats('2026-10-27', {'a.exe': 3, 'b.exe': 7})
    assert temp_db.get_app_total('2026-10-27') == 10


def test_clear_idle_seconds_keeps_count(temp_db):
    """锁屏时长清零，但敲键次数保留（否则总数会对不上）。"""
    temp_db.save_app_stats('2026-10-27', {'lockapp.exe': 5, 'code.exe': 10},
                           {'lockapp.exe': 3600, 'code.exe': 600})

    changed = temp_db.clear_idle_seconds({'lockapp.exe'})
    assert changed == 1

    rows = temp_db.get_app_stats('2026-10-27')
    assert rows['lockapp.exe']['seconds'] == 0
    assert rows['lockapp.exe']['count'] == 5
    assert rows['code.exe']['seconds'] == 600      # 其它应用不受影响


# ---------- 别名解析 ----------
def test_resolve_known_exe():
    info = app_aliases.resolve('chrome.exe')
    assert info['name'] == 'Chrome'
    assert info['category'] == 'browse'


def test_resolve_is_case_insensitive():
    assert app_aliases.resolve('CHROME.EXE')['name'] == 'Chrome'


def test_resolve_unknown_falls_back():
    info = app_aliases.resolve('some_unknown_tool.exe')
    assert info['name'] == 'some_unknown_tool'
    assert info['category'] == 'other'


def test_resolve_empty_is_safe():
    info = app_aliases.resolve('')
    assert info['category'] == 'other'


def test_user_aliases_override_defaults(tmp_path):
    path = tmp_path / 'aliases.json'
    path.write_text('{"chrome.exe": {"name": "谷歌", "category": "work"}}',
                    encoding='utf-8')
    table = app_aliases.load_aliases(str(path), force=True)
    assert table['chrome.exe'] == {'name': '谷歌', 'category': 'work'}
    # 未覆盖的内置项仍然保留
    assert table['code.exe']['name'] == 'VS Code'
    app_aliases.load_aliases(force=True)   # 还原缓存


def test_broken_alias_file_falls_back(tmp_path):
    path = tmp_path / 'bad.json'
    path.write_text('{not json', encoding='utf-8')
    table = app_aliases.load_aliases(str(path), force=True)
    assert table['code.exe']['name'] == 'VS Code'
    app_aliases.load_aliases(force=True)


# ---------- tracker ----------
class FakeSampler:
    """可切换当前 exe 的假采样器。"""

    def __init__(self, exe):
        self.exe = exe

    def current(self):
        return self.exe


def test_record_key_counts_per_app():
    sampler = FakeSampler('code.exe')
    tracker = app_usage.AppUsageTracker(
        sampler=sampler, persist=False, now_fn=lambda: '2026-10-27')
    tracker.record_key()
    tracker.record_key()
    sampler.exe = 'chrome.exe'
    tracker.record_key()

    data = tracker.today()
    assert data['code.exe']['count'] == 2
    assert data['chrome.exe']['count'] == 1
    assert tracker.today_total() == 3


def test_record_key_falls_back_to_unattributed():
    """采样失败不丢弃，归到「未识别」。

    丢弃会让「总次数」比「各应用明细之和」多出一截，
    表现就是气泡 531、分布 517 对不上。
    """
    sampler = FakeSampler(None)
    tracker = app_usage.AppUsageTracker(
        sampler=sampler, persist=False, now_fn=lambda: '2026-10-27')
    assert tracker.record_key() is True
    assert tracker.today()[app_usage.UNATTRIBUTED]['count'] == 1
    assert tracker.today_total() == 1


def test_rollover_clears_memory_when_not_persisting():
    day = {'v': '2026-10-27'}
    sampler = FakeSampler('code.exe')
    tracker = app_usage.AppUsageTracker(
        sampler=sampler, persist=False, now_fn=lambda: day['v'])
    tracker.record_key()
    assert tracker.today_total() == 1

    day['v'] = '2026-10-28'
    tracker.record_key()
    assert tracker.today_total() == 1       # 新的一天重新从 1 开始
    assert tracker.today() == {'code.exe': {'count': 1, 'seconds': 0}}


def test_rollover_persists_previous_day(temp_db):
    day = {'v': '2026-10-27'}
    sampler = FakeSampler('code.exe')
    tracker = app_usage.AppUsageTracker(
        sampler=sampler, persist=True, now_fn=lambda: day['v'])
    tracker.record_key()
    tracker.record_key()

    day['v'] = '2026-10-28'
    tracker.record_key()

    # 旧的一天应已归档到库里
    assert temp_db.get_app_stats('2026-10-27')['code.exe']['count'] == 2
    assert tracker.today()['code.exe']['count'] == 1


def test_restore_aligns_with_total(temp_db):
    """重启后若总数大于明细之和，差额补进「未识别」，两个数字对上。"""
    temp_db.save_count('2026-10-27', 20)
    temp_db.save_app_stats('2026-10-27', {'code.exe': 15})

    tracker = app_usage.AppUsageTracker(
        persist=True, now_fn=lambda: '2026-10-27')

    data = tracker.today()
    assert data['code.exe']['count'] == 15
    assert data[app_usage.UNATTRIBUTED]['count'] == 5
    assert tracker.today_total() == 20


# ---------- JSON 导出 ----------
def test_build_snapshot_structure(temp_db):
    temp_db.save_app_stats('2026-10-26', {'chrome.exe': 100}, {'chrome.exe': 3600})
    temp_db.save_app_stats('2026-10-27', {'code.exe': 40}, {'code.exe': 600})

    snap = stats_export.build_snapshot(today='2026-10-27')

    assert snap['today']['date'] == '2026-10-27'
    assert snap['today']['total_count'] == 40
    assert snap['recent']['days'] == 7
    assert snap['recent']['from'] == '2026-10-21'
    assert snap['recent']['to'] == '2026-10-27'

    apps = {a['exe']: a for a in snap['recent']['apps']}
    assert apps['chrome.exe']['count'] == 100
    assert apps['chrome.exe']['name'] == 'Chrome'
    assert apps['chrome.exe']['category'] == 'browse'


def test_build_snapshot_live_values_override_db(temp_db):
    temp_db.save_app_stats('2026-10-27', {'code.exe': 10})
    snap = stats_export.build_snapshot(
        today='2026-10-27',
        live_today={'code.exe': {'count': 99, 'seconds': 120}},
    )
    assert snap['today']['total_count'] == 99


def test_share_is_fraction(temp_db):
    temp_db.save_app_stats('2026-10-27', {'a.exe': 75, 'b.exe': 25})
    snap = stats_export.build_snapshot(today='2026-10-27')
    shares = {a['exe']: a['count_share'] for a in snap['today']['apps']}
    assert shares['a.exe'] == 0.75
    assert shares['b.exe'] == 0.25


def test_write_json_creates_file(temp_db, tmp_path):
    temp_db.save_app_stats('2026-10-27', {'code.exe': 5})
    out = tmp_path / 'app_stats.json'
    path = stats_export.write_json(path=str(out), days=7)
    assert path == str(out)
    assert out.exists()
    text = out.read_text(encoding='utf-8')
    assert 'code.exe' in text
