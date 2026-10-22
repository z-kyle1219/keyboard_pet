"""weather_loop 逻辑单元测试（pytest）。

用假时钟模拟时间流转，不联网、秒级跑完。
运行：uv run pytest
"""
from datetime import datetime

import scheduler

MAX_TICKS = 30


class _Stop(Exception):
    pass


def _run(timeline, weather_seq, confirm_after=None):
    """跑一次 weather_loop，返回播报调用列表。

    timeline: [(hour, minute)] 逐次返回的时间
    weather_seq: 逐次 fetch 的天气（用完返回 None）
    confirm_after: 第几次 show 之后模拟用户点「知道了」
    """
    calls = []
    state = {"i": 0}
    weather_iter = iter(weather_seq)
    st = scheduler.WeatherState()

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
        if old and old.get("now", {}).get("text") != new.get("now", {}).get("text"):
            ch.append("阴晴变化")
        return ch

    def fake_show(cur, ch):
        calls.append((cur, ch))
        if confirm_after is not None and len(calls) == confirm_after:
            st.confirm("2026-10-22")

    try:
        scheduler.weather_loop(
            show=fake_show, state=st, interval=1, mutation_interval=1,
            sleep_fn=fake_sleep, now_fn=fake_now,
            fetch_all=fake_fetch, detect_change=fake_detect,
        )
    except _Stop:
        pass
    return calls


def _w(text, temp):
    """构造一份单地点天气快照（新结构）。"""
    return {"沙河": {"now": {"text": text, "temp": temp, "wind_scale": "3"},
                     "tomorrow": None, "periods": [], "strip": []}}


def test_outside_window_no_broadcast():
    """窗口外（18 点）不播报。"""
    calls = _run([(18, 0), (18, 1)], [_w("晴", 20), _w("晴", 20)])
    assert len(calls) == 0


def test_broadcast_once_only():
    """未确认时进入窗口只弹一次（挂着，不重复弹）。"""
    calls = _run([(19, 0), (19, 10), (19, 20)], [_w("晴", 20)] * 3)
    assert len(calls) == 1


def test_no_repeat_after_confirm():
    """点「知道了」后，无突变则不再播报。"""
    calls = _run([(19, 0), (19, 10), (19, 20)], [_w("晴", 20)] * 3,
                 confirm_after=1)
    assert len(calls) == 1


def test_mutation_after_confirm_rebroadcast():
    """已确认后阴晴变化 → 兜底再播。"""
    calls = _run([(19, 0), (19, 10), (19, 20)],
                 [_w("晴", 20), _w("晴", 20), _w("阴", 20)],
                 confirm_after=1)
    assert len(calls) == 2
    assert calls[-1][1]
