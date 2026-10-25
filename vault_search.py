"""密码本模糊匹配（纯函数，无副作用，便于单元测试）。

需求原话：“不需要完全匹配，比如 github 和 GitHub 这种是一样的，
有相关字段出现就自动检索”。

因此匹配不是数据库的精确查询，而是一个字符串打分问题：
1. **归一化**：统一小写、去掉空格/连字符/下划线/点等分隔符，
   于是 GitHub / github / git-hub / Git_Hub 归一到同一形态。
2. **多字段加权**：账号名、网址(含域名)、备注/别名各算一路，
   取各自最高分。
3. **包含优先 + 前缀优先**：完全相等最高，前缀命中次之，
   子串命中再次，保证“打一半就能搜到”。
4. **别名命中**：别名（aliases）里的任一条命中都给分，
   方便给 GitHub 挂上 gh / github.com 之类的关键词。

本模块只做“打分 + 排序”，不碰任何 UI / 数据库 / 加密。
"""
import re

# 归一化时剔除的分隔符与噪声字符（含常见网址前后缀）
_NOISE = re.compile(r'[\s\-_.·/@:;,#\[\]()（）【】]+')

# 各路字段的权重（命中越靠前的字段，排序越优先）
_W_NAME = 1.00
_W_DOMAIN = 0.92
_W_ALIAS = 0.88
_W_NOTE = 0.50


def normalize(text):
    """把文本归一化为「可比较形态」：小写 + 去掉分隔符。

    GitHub / github / git-hub / Git_Hub → 'github'
    https://github.com → 'httpsgithubcom'（域名一路会再单独抽取）
    """
    if not text:
        return ''
    return _NOISE.sub('', text.strip().lower())


def extract_domain(url):
    """从网址里抽主要域名（去掉协议与 www.），失败则返回归一化后的原串。

    https://www.github.com/login → 'githubcom'
    github.com → 'githubcom'
    """
    if not url:
        return ''
    host = url.strip().lower()
    # 去掉协议头
    host = re.sub(r'^[a-z]+://', '', host)
    # 去掉路径/查询/端口
    host = re.split(r'[/?#]', host)[0]
    host = host.split(':')[0]
    # 去掉 www. 前缀
    host = re.sub(r'^www\.', '', host)
    return normalize(host)


def _score_one(needle, hay):
    """单个词对单个字段的打分（needle / hay 均已归一化）。

    - 完全相等：1.0
    - 前缀命中：0.8（越接近全长越高）
    - 子串命中：0.6（越靠前越高）
    - 未命中：0
    """
    if not needle or not hay:
        return 0.0
    if needle == hay:
        return 1.0
    if hay.startswith(needle):
        return 0.8 + 0.15 * (len(needle) / len(hay))
    idx = hay.find(needle)
    if idx >= 0:
        # 越靠前的子串命中给分越高（0.6 → 0.75 区间）
        return 0.6 + 0.15 * (1 - idx / len(hay))
    return 0.0


def score(query, row):
    """给一条账号记录打分，返回 0.0~1.0（0 表示不命中）。

    query: 用户输入的搜索词
    row:   映射，需含 name / url / aliases / note 字段
           （aliases 为可迭代的别名；其它为字符串，缺失按空处理）

    规则：把 query 整串与各字段比一遍，取加权后的最高分；
    别名列表里每条别名都参与比对，取最好的一条。
    """
    q = normalize(query)
    if not q:
        return 0.0

    best = 0.0

    name = normalize(row.get('name'))
    best = max(best, _score_one(q, name) * _W_NAME)

    domain = extract_domain(row.get('url') or '')
    best = max(best, _score_one(q, domain) * _W_DOMAIN)
    # 网址整串也参与（用户可能直接粘完整链接搜索）
    url_norm = normalize(row.get('url'))
    best = max(best, _score_one(q, url_norm) * _W_DOMAIN)

    for alias in (row.get('aliases') or []):
        best = max(best, _score_one(q, normalize(alias)) * _W_ALIAS)

    note = normalize(row.get('note'))
    best = max(best, _score_one(q, note) * _W_NOTE)

    return best


def search(query, rows, limit=None):
    """在 rows 里按 query 模糊检索，返回按分数降序的记录列表。

    rows: 可迭代的映射（每个含 id / name / url / aliases / note 等）。
    命中（分数 > 0）才返回；分数相同时按名称字母序稳定排序。
    """
    scored = []
    for r in rows:
        s = score(query, r)
        if s > 0:
            scored.append((s, r))
    scored.sort(key=lambda t: (-t[0], str(t[1].get('name', '')).lower()))
    result = [r for _s, r in scored]
    if limit is not None:
        result = result[:limit]
    return result
