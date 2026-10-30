"""近 7 天聚合的边界用例：两端闭区间，窗口外一天都不算。

时间范围一律用单表 GROUP BY 现算、不建汇总表——所以「边界算不算」
直接决定折线图和 app_stats.json 里的数字对不对。
"""
import pytest

import db
from stats_export import build_snapshot


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """把 db 层的库指向临时文件，保证测试隔离。"""
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'window_test.db'))
    return db


def test_seven_day_window_includes_both_endpoints(temp_db):
    """起点和终点都算，窗口前一天和后一天都不算。"""
    temp_db.save_app_stats('2026-10-20', {'code.exe': 1000})   # 窗口外（更早）
    temp_db.save_app_stats('2026-10-21', {'code.exe': 1})      # 起点
    temp_db.save_app_stats('2026-10-24', {'code.exe': 2})      # 中间
    temp_db.save_app_stats('2026-10-27', {'code.exe': 4})      # 终点（今天）
    temp_db.save_app_stats('2026-10-28', {'code.exe': 8000})   # 窗口外（未来）

    snap = build_snapshot(today='2026-10-27')

    assert snap['recent']['from'] == '2026-10-21'
    assert snap['recent']['to'] == '2026-10-27'
    counts = {a['exe']: a['count'] for a in snap['recent']['apps']}
    assert counts['code.exe'] == 7           # 1 + 2 + 4


def test_aggregate_until_date_is_inclusive(temp_db):
    """until_date 是闭区间：27 号的记录要算进来，28 号的不算。"""
    temp_db.save_app_stats('2026-10-20', {'a.exe': 100})
    temp_db.save_app_stats('2026-10-21', {'a.exe': 1})
    temp_db.save_app_stats('2026-10-27', {'a.exe': 2})
    temp_db.save_app_stats('2026-10-28', {'a.exe': 200})

    assert temp_db.get_app_aggregate('2026-10-21', '2026-10-27') == [
        ('a.exe', 3, 0)
    ]


def test_window_rolls_with_today(temp_db):
    """窗口跟着「今天」走：今天 28 号，起点自动变成 22 号。"""
    temp_db.save_app_stats('2026-10-21', {'a.exe': 9})    # 已滑出窗口
    temp_db.save_app_stats('2026-10-22', {'a.exe': 1})    # 新起点

    snap = build_snapshot(today='2026-10-28')

    assert snap['recent']['from'] == '2026-10-22'
    counts = {a['exe']: a['count'] for a in snap['recent']['apps']}
    assert counts['a.exe'] == 1


def test_window_crosses_month_boundary(temp_db):
    """跨月也算对：3 月 1 日的近 7 天起点是 2 月 23 日。"""
    snap = build_snapshot(today='2026-03-01')

    assert snap['recent']['from'] == '2026-02-23'
    assert snap['recent']['to'] == '2026-03-01'


def test_single_day_window_collapses_to_today(temp_db):
    """days=1 时起点等于终点，不会算出负区间。"""
    snap = build_snapshot(today='2026-10-27', days=1)

    assert snap['recent']['from'] == '2026-10-27'
    assert snap['recent']['to'] == '2026-10-27'


def test_empty_window_returns_empty_list(temp_db):
    """库里没数据时返回空列表而不是报错（首次运行的第一天）。"""
    snap = build_snapshot(today='2026-10-27')

    assert snap['recent']['apps'] == []
    assert snap['recent']['total_count'] == 0
    assert temp_db.get_app_aggregate('2026-10-27', '2026-10-27') == []
