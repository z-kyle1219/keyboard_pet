"""翻译模块：中英互译（百度翻译开放平台）。

设计要点（与 weather.py 同一套路）：
- 纯逻辑，不碰界面，可单独在命令行验证：python translate.py hello
- 自动判断方向：含汉字 → 译成英文；否则 → 译成中文
- APPID / 密钥从 .env 或环境变量读取，绝不写进代码
- 所有网络/解析异常都兜底，统一返回 TranslateResult，不抛给调用方
- 带内存 LRU 缓存：同一个词/句不重复请求（省额度，重复查询瞬回）

百度文档：https://fanyi-api.baidu.com/doc/21
"""
import hashlib
import os
import random
import threading
from collections import OrderedDict
from dataclasses import dataclass

import requests

from logger import logger

# 自动加载同目录下的 .env（与 weather.py 保持同一约定）
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
# 配置
# ============================================================
API_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"

# 请求超时（秒）：桌宠要"秒出"，宁可失败重试也不要挂着
TIMEOUT = 5

# 单次最长字符数（百度上限 6000 字节，这里按字符收紧，防手滑粘一整篇）
MAX_CHARS = 2000

# 内存缓存条数
CACHE_SIZE = 256

# 环境变量名（.env 里同名）
ENV_APPID = "BAIDU_APPID"
ENV_KEY = "BAIDU_KEY"

# 常见错误码 → 人话（未知码回退 error_msg）
_ERROR_HINTS = {
    "52001": "翻译请求超时，稍后再试",
    "52002": "翻译服务开小差了，稍后再试",
    "52003": "APPID 或密钥不对，检查一下 .env",
    "54000": "内容为空，没有可翻译的文字",
    "54001": "签名错误，检查密钥是否填错",
    "54003": "免费额度用完了或请求太频繁",
    "54004": "账户余额不足",
    "54005": "请求太频繁，缓一下再来",
    "58000": "客户端 IP 不在白名单内",
    "58001": "不支持这个翻译方向",
    "58002": "翻译服务已关闭",
    "90107": "认证还没生效，等一会儿再试",
}


@dataclass
class TranslateResult:
    """统一的翻译结果：界面只认这一种形状。"""

    ok: bool
    src: str = ""            # 原文
    dst: str = ""            # 译文
    direction: str = ""      # 'en2zh' / 'zh2en'
    error: str = ""          # 失败原因（人话）
    cached: bool = False     # 是否直接来自缓存

    @property
    def label(self):
        if self.direction == "zh2en":
            return "中 → 英"
        if self.direction == "en2zh":
            return "英 → 中"
        return "翻译"


# ============================================================
# 方向判断
# ============================================================
def has_chinese(text):
    """文本里是否含汉字（CJK 统一表意文字）。"""
    return any('\u4e00' <= ch <= '\u9fff' for ch in text)


def detect_direction(text):
    """推断翻译方向：含汉字就当"中译英"，否则当"英译中"。

    中英混排（如「这个 API 怎么用」）按中文处理，译成英文更符合直觉。
    """
    return "zh2en" if has_chinese(text) else "en2zh"


def has_translatable(text):
    """至少有一个字母或汉字才值得翻译（纯数字/符号直接拦掉）。"""
    return any(ch.isalpha() or '\u4e00' <= ch <= '\u9fff' for ch in text)


# ============================================================
# 内存 LRU 缓存（线程安全）
# ============================================================
_cache = OrderedDict()
_cache_lock = threading.Lock()


def _cache_get(key):
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    return None


def _cache_put(key, value):
    with _cache_lock:
        _cache[key] = value
        _cache.move_to_end(key)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def clear_cache():
    """清空缓存（测试用）。"""
    with _cache_lock:
        _cache.clear()


# ============================================================
# 翻译
# ============================================================
def _config():
    return (os.environ.get(ENV_APPID, "").strip(),
            os.environ.get(ENV_KEY, "").strip())


def translate(text, timeout=TIMEOUT):
    """把文本翻译成另一种语言，永远返回 TranslateResult，不抛异常。

    参数：
        text    原文（自动 strip）
        timeout 请求超时秒数
    """
    src = (text or "").strip()
    if not src:
        return TranslateResult(False, error="没有可翻译的内容")
    if not has_translatable(src):
        return TranslateResult(False, src=src, error="这里没有文字，只有符号或数字")

    direction = detect_direction(src)

    if len(src) > MAX_CHARS:
        return TranslateResult(
            False, src=src, direction=direction,
            error=f"太长了（上限 {MAX_CHARS} 字），挑一段再翻吧",
        )

    appid, secret = _config()
    if not appid or not secret:
        return TranslateResult(
            False, src=src, direction=direction,
            error="还没配置百度翻译 APPID / 密钥（填 .env）",
        )

    key = (direction, src)
    hit = _cache_get(key)
    if hit is not None:
        return TranslateResult(True, src=hit[0], dst=hit[1],
                               direction=direction, cached=True)

    to = "en" if direction == "zh2en" else "zh"
    salt = str(random.randint(32768, 65536))
    sign = hashlib.md5(
        (appid + src + salt + secret).encode("utf-8")).hexdigest()
    params = {
        "q": src,
        "from": "auto",
        "to": to,
        "appid": appid,
        "salt": salt,
        "sign": sign,
    }

    try:
        resp = requests.post(API_URL, data=params, timeout=timeout)
        data = resp.json()
    except Exception:
        # 网络不通 / 超时 / 返回不是 JSON：统一兜底，不往上抛
        logger.exception("翻译请求失败")
        return TranslateResult(False, src=src, direction=direction,
                               error="网络不通，稍后再试")

    if not isinstance(data, dict):
        logger.warning("翻译返回格式异常：%r", data)
        return TranslateResult(False, src=src, direction=direction,
                               error="翻译服务返回异常")

    if data.get("error_code"):
        code = str(data["error_code"])
        logger.warning("百度翻译错误 %s：%s", code, data.get("error_msg"))
        return TranslateResult(
            False, src=src, direction=direction,
            error=_ERROR_HINTS.get(code) or data.get("error_msg")
            or "翻译失败",
        )

    items = data.get("trans_result") or []
    dst = "\n".join(str(it.get("dst") or "") for it in items).strip()
    if not dst:
        return TranslateResult(False, src=src, direction=direction,
                               error="没有拿到译文，换个说法试试")

    # 以服务端判定为准（比如纯数字会被识别成别的语种）
    src_lang = str(data.get("from") or "")
    if src_lang in ("zh", "en"):
        direction = "zh2en" if src_lang == "zh" else "en2zh"

    _cache_put(key, (src, dst))
    return TranslateResult(True, src=src, dst=dst, direction=direction)


# ============================================================
# 命令行自测：python translate.py hello
# ============================================================
if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]).strip() or "hello world"
    result = translate(text)
    if result.ok:
        suffix = "（缓存）" if result.cached else ""
        print(f"[{result.label}] {result.src}\n  → {result.dst}{suffix}")
    else:
        print(f"翻译失败：{result.error}")
