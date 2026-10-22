"""天气模块：请求和风天气 API，解析并判断突变。

设计要点：
- 纯逻辑，不碰界面，可单独在命令行运行验证：python weather.py
- 直接使用经纬度查天气（不用 GeoAPI 查 Location ID），少一次请求
- KEY / HOST 从环境变量读取，绝不写进代码
- 所有网络/解析异常都兜底，绝不抛给调用方

坐标格式：经度,纬度（注意先经度后纬度）
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


def fetch_weather(coord, timeout=TIMEOUT):
    """请求某坐标的实时天气，返回精简字典；失败返回 None。

    coord: "经度,纬度"，如 "116.28,40.10"
    返回: {"text": "阴", "temp": 22, "wind_dir": "东南风", "wind_scale": "3"}
    """
    url = f"{_api_base()}/v7/weather/now"
    params = {"location": coord, "key": _api_key()}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        data = resp.json()
    except Exception:
        logger.exception("天气请求失败 coord=%s", coord)
        return None

    if data.get("code") != "200":
        # 非 2xx 的请求不计费，但错误码要记下来便于排查
        logger.warning("天气接口返回异常 code=%s coord=%s",
                       data.get("code"), coord)
        return None

    now = data.get("now", {})
    try:
        return {
            "text": now.get("text", ""),            # 阴晴
            "temp": int(now.get("temp", 0)),        # 温度（℃）
            "wind_dir": now.get("windDir", ""),     # 风向
            "wind_scale": now.get("windScale", ""), # 风力等级
        }
    except Exception:
        logger.exception("天气数据解析失败 coord=%s", coord)
        return None


def fetch_all():
    """拉取所有地点的天气。

    返回: {地点名: 天气字典}，某个地点失败则不在结果里。
    """
    result = {}
    for loc in LOCATIONS:
        weather = fetch_weather(loc["coord"])
        if weather is not None:
            result[loc["name"]] = weather
    return result


def detect_change(old, new):
    """对比上次与本次天气，返回突变描述列表；无突变返回空列表。

    old / new: {"text":..., "temp":..., ...}
    判定：阴晴文字变化，或气温骤降 >= TEMP_DROP_THRESHOLD
    """
    changes = []
    if not old or not new:
        return changes

    if old.get("text") != new.get("text"):
        changes.append(f"{old.get('text')}→{new.get('text')}")

    drop = old.get("temp", 0) - new.get("temp", 0)
    if drop >= TEMP_DROP_THRESHOLD:
        changes.append(f"气温降{drop}℃")

    return changes


if __name__ == "__main__":
    # 命令行自测：python weather.py
    print("=== 天气播报自测 ===")
    all_weather = fetch_all()
    if not all_weather:
        print("没有取到任何天气数据（检查 .env 里的 QWEATHER_KEY / QWEATHER_HOST 或网络）")
    for name, w in all_weather.items():
        print(f"{name}：{w['text']}，风速 {w['wind_scale']} 级，"
              f"气温 {w['temp']}℃")
