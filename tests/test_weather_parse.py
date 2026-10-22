"""weather.py 时段合并与日期过滤的单元测试。

重点回归：72h 数据含今天/明天/后天，必须只取「明天」那一天，
否则会把不同天的天气混在一起（表现为"明天下一整天雨"）。
运行：uv run pytest
"""
import weather


def _h(date, hour, text):
    return {"fxTime": f"{date}T{hour:02d}:00+08:00", "text": text}


def test_pick_tomorrow_only():
    """只保留明天那一天的逐小时数据。"""
    hourly = [
        _h("2026-10-22", 20, "小雨"),   # 今天
        _h("2026-10-22", 23, "小雨"),   # 今天
        _h("2026-10-23", 8, "晴"),      # 明天
        _h("2026-10-23", 14, "多云"),   # 明天
        _h("2026-10-24", 9, "小雨"),    # 后天
    ]
    got = weather._pick_tomorrow_hourly(hourly, "2026-10-23")
    assert len(got) == 2
    assert all(h["fxTime"].startswith("2026-10-23") for h in got)


def test_rain_periods_only_tomorrow():
    """降雨时段只反映明天，不含今天/后天的雨。"""
    hourly = [
        _h("2026-10-22", 20, "小雨"),   # 今天有雨 → 不应出现
        _h("2026-10-23", 8, "晴"),
        _h("2026-10-23", 12, "小雨"),
        _h("2026-10-23", 13, "小雨"),
        _h("2026-10-23", 14, "阴"),
        _h("2026-10-24", 9, "大雨"),    # 后天有雨 → 不应出现
    ]
    day = weather._pick_tomorrow_hourly(hourly, "2026-10-23")
    periods = weather._merge_periods(day, 6, 24, lambda h: weather._is_rain(h["text"]))
    assert len(periods) == 1
    assert periods[0]["start"] == "12:00"
    assert periods[0]["end"] == "14:00"
    assert periods[0]["text"] == "小雨"


def test_strip_no_cross_day_merge():
    """时段条不跨天合并：今天 23 点与明天 6 点不并成一段。"""
    hourly = [
        _h("2026-10-22", 22, "阴"),
        _h("2026-10-22", 23, "阴"),
        _h("2026-10-23", 6, "阴"),   # 与上面隔着 0-5 点
        _h("2026-10-23", 7, "阴"),
    ]
    day = weather._pick_tomorrow_hourly(hourly, "2026-10-23")
    ranges = weather._text_ranges(day, 6, 24)
    # 明天只有 6、7 两点 → 一段 6-8
    assert len(ranges) == 1
    assert ranges[0]["start_h"] == 6
    assert ranges[0]["end_h"] == 8


def test_strip_empty_when_no_tomorrow_data():
    """明天没有数据时，时段与降雨都为空（不误用其它天）。"""
    hourly = [_h("2026-10-22", 20, "小雨")]
    day = weather._pick_tomorrow_hourly(hourly, "2026-10-23")
    assert day == []
