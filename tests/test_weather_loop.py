"""weather_loop 逻辑单元测试（pytest）。

用假时钟模拟时间流转，不联网、秒级跑完。
运行：uv run pytest   （或 uv run pytest tests/ -v）
"""
from datetime import datetime

import scheduler

MAX_TICKS = 30   # 每次用例最多循环次数，防止死循环


class _Stop(Exception):
    """内部用：达到循环上限时中断 weather_loop。"""


def _run(timeline, weather_seq):
    """跑一次 weather_loop，返回播报调用列表。

    timeline: [(hour, minute)] 逐次返回的时间
    weather_seq: 逐次 fetch 的天气（用完返回 None）
    """
    calls = []
    state = {"i": 0}
    weather_iter = iter(weather_seq)

    def fake_now():
        if state["i"] >= MAX_TICKS:
            raise _Stop
        idx = min(state["i"], len(timeline) - 1)
        state["i"] += 1
        h, m = timeline[idx]
        return datetime(2026, 10, 22, h, m)

    def fake_sleep(_):
        pass

    def fake_fetch():
        return next(weather_iter, None)

    def fake_detect(old, new):
        ch = []
        if old and old.get("text") != new.get("text"):
            ch.append("阴晴变化")
        if old and old.get("temp", 0) - new.get("temp", 0) >= 5:
            ch.append("骤降")
        return ch

    try:
        scheduler.weather_loop(
            show=lambda cur, ch: calls.append((cur, ch)),
            state=scheduler.WeatherState(),
            interval=1,
            sleep_fn=fake_sleep,
            now_fn=fake_now,
            fetch_all=fake_fetch,
            detect_change=fake_detect,
        )
    except _Stop:
        pass
    return calls


def _w(text, temp):
    """构造一份单地点天气快照。"""
    return {"沙河": {"text": text, "temp": temp, "wind_scale": "3"}}


def test_outside_window_no_broadcast():
    """窗口外（18 点）不播报。"""
    calls = _run([(18, 0), (18, 1)], [_w("晴", 20), _w("晴", 20)])
    assert len(calls) == 0


def test_first_broadcast_then_silent():
    """窗口内首次播报一次；已确认且无变化 → 静默。"""
    calls = _run([(19, 0), (19, 30), (20, 0)], [_w("晴", 20)] * 3)
    assert len(calls) == 1


def test_change_triggers_rebroadcast():
    """已确认后阴晴变化 → 兜底再播。"""
    calls = _run([(19, 0), (19, 30), (20, 0)],
                 [_w("晴", 20), _w("晴", 20), _w("阴", 20)])
    assert len(calls) == 2
    assert calls[-1][1]   # 最后一次带突变描述


def test_temp_drop_triggers_rebroadcast():
    """已确认后气温骤降 ≥5℃ → 兜底再播。"""
    calls = _run([(19, 0), (19, 30)], [_w("晴", 20), _w("晴", 13)])
    assert len(calls) == 2
