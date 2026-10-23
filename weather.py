"""天气模块：请求和风天气 API，解析、组装并判断突变。

设计要点：
- 纯逻辑，不碰界面，可单独在命令行运行验证：python weather.py
- 直接使用经纬度查天气（不用 GeoAPI 查 Location ID）
- KEY / HOST 从环境变量读取，绝不写进代码
- 所有网络/解析异常都兜底，绝不抛给调用方

坐标格式：经度,纬度（注意先经度后纬度）

每个地点一次取三份数据：
- now   实况（现在多少度、阴晴、风）
- 3d    未来 3 天（取今天与明天的最高/最低温，做白天/夜间对比）
- 72h   未来 72 小时（逐小时，用于"阴晴变化时段条"与"降雨时段"）
"""
import os

import requests

from logger import logger

# 自动加载同目录下的 .env（无需手动注入环境变量）
# 没有 .env 时静默跳过，仍可用系统环境变量
try:
    from pathlib import Path
    _env_path = Path(__file__).with_name(".env")
    if _env_path.exists():
        for _line in _env_path.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())
except Exception:
    logger.exception("加载 .env 失败")

# ============================================================
# 配置：改这里即可换地点（别人 copy 代码只需改这一处）
# ============================================================
LOCATIONS = [
    {"name": "北京邮电大学 · 沙河校区", "coord": "116.28,40.10"},
    {"name": "大连理工大学 · 凌水校区", "coord": "121.52,38.88"},
]

# 突变阈值：气温比上次播报降 >= 这个值，算"骤降"
TEMP_DROP_THRESHOLD = 5

# 请求超时（秒）
TIMEOUT = 10

# 时段条时间轴：06:00–24:00（明天白天到夜里）
STRIP_START_HOUR = 6
STRIP_END_HOUR = 24


def _api_base():
    """从环境变量取 API Host，拼成 https 地址。"""
    host = os.environ.get("QWEATHER_HOST")
    if not host:
        raise RuntimeError("缺少环境变量 QWEATHER_HOST")
    return f"https://{host}"


def _api_key():
    """从环境变量取 API Key。"""
    key = os.environ.get("QWEATHER_KEY")
    if not key:
        raise RuntimeError("缺少环境变量 QWEATHER_KEY")
    return key


def _get(path, coord, timeout=TIMEOUT):
    """通用请求：返回解析后的 dict；失败返回 None。"""
    try:
        url = f"{_api_base()}{path}"
        params = {"location": coord, "key": _api_key()}
        resp = requests.get(url, params=params, timeout=timeout)
        data = resp.json()
    except Exception:
        logger.exception("天气请求失败 path=%s coord=%s", path, coord)
        return None
    if data.get("code") != "200":
        logger.warning("天气接口返回异常 code=%s path=%s coord=%s",
                       data.get("code"), path, coord)
        return None
    return data


def _is_rain(text):
    """判断天气文字是否含降水。"""
    return any(k in text for k in ("雨", "雪", "雷"))


def _hour_of(item):
    """从 fxTime "2026-10-23T14:00+08:00" 取小时整数。"""
    try:
        return int(item["fxTime"][11:13])
    except Exception:
        return None


def _date_of(item):
    """从 fxTime 取日期 "2026-10-23"。"""
    try:
        return item["fxTime"][:10]
    except Exception:
        return None


def _pick_tomorrow_hourly(hourly, tomorrow_date):
    """只保留**明天那一天**的逐小时数据。

    这是关键：72h 数据从"现在"起算，会同时含今天/明天/后天，
    不过滤就会把不同天的天气混在一起（导致"明天下一整天雨"的错觉）。
    """
    if not tomorrow_date:
        return []
    return [h for h in hourly if _date_of(h) == tomorrow_date]


def _merge_periods(hourly, start_hour, end_hour, predicate):
    """把逐小时数据里满足 predicate 的连续时段合并。

    hourly: [{"fxTime":..., "text":...}, ...]（已按时间排序）
    返回: [{"start": "14:00", "end": "16:00", "text": "小雨"}, ...]
    end 为该时段最后一个小时的**下一个整点**（表示区间结束）。
    """
    periods = []
    cur = None
    prev_h = None
    for h in hourly:
        hh = _hour_of(h)
        if hh is None:
            continue
        if not (start_hour <= hh < end_hour):
            prev_h = None   # 离开轴范围，打断连续性
            continue
        ok = predicate(h)
        if ok:
            if (cur is not None and prev_h is not None
                    and hh == prev_h + 1):
                cur["end_h"] = hh + 1
                cur["text"] = h.get("text", cur["text"])
            else:
                if cur is not None:
                    periods.append(cur)
                cur = {"start_h": hh, "end_h": hh + 1, "text": h.get("text", "")}
        else:
            if cur is not None:
                periods.append(cur)
                cur = None
        prev_h = hh
    if cur is not None:
        periods.append(cur)
    return [{"start": f"{p['start_h']:02d}:00",
             "end": f"{p['end_h']:02d}:00",
             "text": p["text"]} for p in periods]


def _text_ranges(hourly, start_hour, end_hour):
    """把逐小时的天气文字合并成变化时段（用于时段条）。

    只在**相邻小时**且文字相同才合并；跨天/跳时段（如今天 23 点
    与明天 6 点之间隔着 0–5 点）不合并，避免出现 start>end 的非法段。

    返回: [{"start_h":6, "end_h":9, "text":"阴"}, ...]
    """
    ranges = []
    cur = None
    prev_h = None
    for h in hourly:
        try:
            hh = int(h["fxTime"][11:13])
        except Exception:
            continue
        if not (start_hour <= hh < end_hour):
            prev_h = None   # 离开轴范围，打断连续性
            continue
        t = h.get("text", "")
        # 与上一段连续（相邻小时）且文字相同 → 延长；否则开新段
        if (cur is not None and prev_h is not None
                and hh == prev_h + 1 and t == cur["text"]):
            cur["end_h"] = hh + 1
        else:
            if cur is not None:
                ranges.append(cur)
            cur = {"start_h": hh, "end_h": hh + 1, "text": t}
        prev_h = hh
    if cur is not None:
        ranges.append(cur)
    return ranges


def fetch_location(coord):
    """取一个地点的完整天气（实况 + 明天预报 + 时段）。

    返回 dict：
    {
      "now":  {"text","temp","wind_scale"},
      "tomorrow": {
          "date": "2026-10-23",
          "brief": "多云转阴",        # textDay 转 textNight
          "day_temp": 22, "night_temp": 14,
          "day_delta": -3,            # 比今天白天（正=暖，负=冷）
          "night_delta": +1,
      },
      "periods": [{"start":"14:00","end":"16:00","text":"小雨"}, ...],
      "strip": [{"start_h":6,"end_h":9,"text":"阴"}, ...],
    }
    失败返回 None。
    """
    now_data = _get("/v7/weather/now", coord)
    if not now_data:
        return None
    daily = (_get("/v7/weather/3d", coord) or {}).get("daily", [])
    hourly = (_get("/v7/weather/72h", coord) or {}).get("hourly", [])

    now = now_data.get("now", {})
    result = {
        "now": {
            "text": now.get("text", ""),
            "temp": int(now.get("temp", 0) or 0),
            "wind_scale": now.get("windScale", ""),
        },
        "tomorrow": None,
        "periods": [],
        "strip": [],
    }

    # 明天预报 + 与今天对比
    if len(daily) >= 2:
        today, tmrw = daily[0], daily[1]
        td = tmrw.get("textDay", "")
        tn = tmrw.get("textNight", "")
        brief = td if td == tn else f"{td}转{tn}"

        def _i(v):
            try:
                return int(v)
            except Exception:
                return None

        t_max, t_min = _i(tmrw.get("tempMax")), _i(tmrw.get("tempMin"))
        y_max, y_min = _i(today.get("tempMax")), _i(today.get("tempMin"))
        result["tomorrow"] = {
            "date": tmrw.get("fxDate", ""),
            "brief": brief,
            "day_temp": t_max,
            "night_temp": t_min,
            "day_delta": (t_max - y_max) if (t_max is not None and y_max is not None) else None,
            "night_delta": (t_min - y_min) if (t_min is not None and y_min is not None) else None,
        }

    # 降雨时段 + 阴晴变化时段条
    # 关键：只取**明天那一天**的逐小时数据（72h 会含今天/明天/后天）
    tomorrow_date = (result.get("tomorrow") or {}).get("date")
    day_hourly = _pick_tomorrow_hourly(hourly, tomorrow_date)
    if day_hourly:
        result["periods"] = _merge_periods(
            day_hourly, STRIP_START_HOUR, STRIP_END_HOUR,
            lambda h: _is_rain(h.get("text", "")))
        result["strip"] = _text_ranges(day_hourly, STRIP_START_HOUR, STRIP_END_HOUR)

    return result


def fetch_all():
    """拉取所有地点的天气。

    返回: {地点名: 地点数据字典}，某个地点失败则不在结果里。
    """
    result = {}
    for loc in LOCATIONS:
        data = fetch_location(loc["coord"])
        if data is not None:
            result[loc["name"]] = data
    return result


def detect_change(old, new):
    """对比上次与本次天气，返回突变描述列表；无突变返回空列表。

    old / new: 地点数据字典（含 now / tomorrow）
    判定（实况 + 预报都看）：
    - 实况阴晴文字变化
    - 实况气温骤降 >= TEMP_DROP_THRESHOLD
    - 明天预报阴晴变化（brief 不同）
    - 明天白天/夜间预报温度骤降 >= TEMP_DROP_THRESHOLD
    """
    changes = []
    if not old or not new:
        return changes

    o_now, n_now = old.get("now", {}), new.get("now", {})
    o_tm, n_tm = old.get("tomorrow") or {}, new.get("tomorrow") or {}

    # ---- 实况对比 ----
    if o_now.get("text") != n_now.get("text"):
        changes.append(f"现在 {o_now.get('text')}→{n_now.get('text')}")

    drop = (o_now.get("temp", 0) or 0) - (n_now.get("temp", 0) or 0)
    if drop >= TEMP_DROP_THRESHOLD:
        changes.append(f"现在气温降{drop}℃")

    # ---- 明天预报对比（关键：预报变化也要提醒）----
    o_brief, n_brief = o_tm.get("brief", ""), n_tm.get("brief", "")
    if o_brief and n_brief and o_brief != n_brief:
        changes.append(f"明天预报 {o_brief}→{n_brief}")

    # 明天白天/夜间温度预报变化（降 >= 阈值）
    for key, label in (("day_temp", "白天"), ("night_temp", "夜间")):
        ov, nv = o_tm.get(key), n_tm.get(key)
        if ov is not None and nv is not None and (ov - nv) >= TEMP_DROP_THRESHOLD:
            changes.append(f"明天{label}预报降{ov - nv}℃")

    return changes


if __name__ == "__main__":
    # 命令行自测：python weather.py
    print("=== 天气播报自测 ===")
    all_weather = fetch_all()
    if not all_weather:
        print("没有取到任何天气数据（检查 .env 里的 QWEATHER_KEY / QWEATHER_HOST 或网络）")
    for name, d in all_weather.items():
        n = d["now"]
        print(f"{name}：现在 {n['text']} {n['temp']}℃ 风{n['wind_scale']}级")
        t = d.get("tomorrow")
        if t:
            print(f"    明天 {t['brief']}　白天 {t['day_temp']}°　夜间 {t['night_temp']}°"
                  f"　对比 {t['day_delta']}/{t['night_delta']}")
        for p in d.get("periods", []):
            print(f"    🌧 {p['start']}–{p['end']} {p['text']}")
        if d.get("strip"):
            print("    时段条：" + " → ".join(
                f"{r['start_h']:02d}–{r['end_h']:02d}{r['text']}" for r in d["strip"]))
