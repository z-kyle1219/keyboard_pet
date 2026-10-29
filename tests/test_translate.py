"""翻译模块回归用例：只测纯逻辑，绝不联网。

覆盖：
- 方向判断（英→中 / 中→英 / 中英混排）
- 正常响应解析与缓存命中
- 服务端错误码 → 人话提示
- 网络异常兜底
- 空内容 / 超长 / 没配置密钥
"""
import translate


class _FakeResp:
    """伪造 requests 响应，只需要 .json()。"""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _set_key(monkeypatch):
    monkeypatch.setenv(translate.ENV_APPID, 'test-appid')
    monkeypatch.setenv(translate.ENV_KEY, 'test-key')
    translate.clear_cache()


# ---------------- 方向判断 ----------------
def test_detect_direction_english():
    assert translate.detect_direction('hello world') == 'en2zh'


def test_detect_direction_chinese():
    assert translate.detect_direction('你好') == 'zh2en'


def test_detect_direction_mixed_counts_as_chinese():
    # 中英混排按中文处理，译成英文更符合直觉
    assert translate.detect_direction('这个 API 怎么用') == 'zh2en'


def test_has_translatable():
    assert translate.has_translatable('abc')
    assert translate.has_translatable('你好')
    assert not translate.has_translatable('123 !!! ---')


# ---------------- 正常请求 ----------------
def test_translate_parses_and_caches(monkeypatch):
    _set_key(monkeypatch)
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append(data)
        return _FakeResp({
            'from': 'en', 'to': 'zh',
            'trans_result': [{'src': 'hello', 'dst': '你好'}],
        })

    monkeypatch.setattr(translate.requests, 'post', fake_post)

    first = translate.translate('hello')
    assert first.ok
    assert first.dst == '你好'
    assert first.direction == 'en2zh'
    assert first.cached is False
    assert calls[0]['to'] == 'zh'
    assert calls[0]['from'] == 'auto'
    # 参数齐全，签名是 32 位 md5
    for name in ('q', 'appid', 'salt', 'sign'):
        assert calls[0][name]
    assert len(calls[0]['sign']) == 32

    # 第二次应该命中缓存，不再发请求
    calls.clear()
    second = translate.translate('hello')
    assert second.ok and second.cached is True
    assert second.dst == '你好'
    assert calls == []


def test_translate_chinese_to_english(monkeypatch):
    _set_key(monkeypatch)

    def fake_post(url, data=None, timeout=None):
        assert data['to'] == 'en'
        return _FakeResp({
            'from': 'zh', 'to': 'en',
            'trans_result': [{'src': '你好', 'dst': 'Hello'}],
        })

    monkeypatch.setattr(translate.requests, 'post', fake_post)
    result = translate.translate('你好')
    assert result.ok
    assert result.dst == 'Hello'
    assert result.direction == 'zh2en'


def test_translate_multiline_joins(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(
        translate.requests, 'post',
        lambda *a, **k: _FakeResp({
            'from': 'en', 'to': 'zh',
            'trans_result': [{'src': 'a', 'dst': '甲'},
                             {'src': 'b', 'dst': '乙'}],
        }),
    )
    result = translate.translate('a\nb')
    assert result.dst == '甲\n乙'


# ---------------- 失败兜底 ----------------
def test_translate_api_error_is_friendly(monkeypatch):
    _set_key(monkeypatch)
    monkeypatch.setattr(
        translate.requests, 'post',
        lambda *a, **k: _FakeResp({
            'error_code': '54003', 'error_msg': 'Invalid Access Limit'}),
    )
    result = translate.translate('hello')
    assert not result.ok
    assert '频繁' in result.error


def test_translate_network_error(monkeypatch):
    _set_key(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError('network down')

    monkeypatch.setattr(translate.requests, 'post', boom)
    result = translate.translate('hello')
    assert not result.ok
    assert '网络' in result.error


def test_translate_empty():
    result = translate.translate('   ')
    assert not result.ok
    assert '没有' in result.error


def test_translate_no_letters():
    result = translate.translate('12345 !!!')
    assert not result.ok


def test_translate_too_long(monkeypatch):
    _set_key(monkeypatch)
    result = translate.translate('a' * (translate.MAX_CHARS + 1))
    assert not result.ok
    assert '太长' in result.error


def test_translate_without_key(monkeypatch):
    monkeypatch.delenv(translate.ENV_APPID, raising=False)
    monkeypatch.delenv(translate.ENV_KEY, raising=False)
    result = translate.translate('hello')
    assert not result.ok
    assert 'APPID' in result.error
