"""vault_search 模糊匹配的单元测试。

重点回归用户诉求：“github 和 GitHub 这种是一样的，有相关字段
出现就自动检索”。运行：uv run pytest
"""
import vault_search as vs


# ---------- 归一化 ----------
def test_normalize_case_and_separators():
    """大小写与分隔符归一：GitHub / github / git-hub 应一致。"""
    assert vs.normalize('GitHub') == vs.normalize('github')
    assert vs.normalize('Git-Hub') == 'github'
    assert vs.normalize('Git_Hub') == 'github'
    assert vs.normalize(' git hub ') == 'github'


def test_extract_domain_strips_scheme_and_www():
    """网址抽域名：去协议、去 www、去路径。"""
    assert vs.extract_domain('https://www.github.com/login') == 'githubcom'
    assert vs.extract_domain('github.com') == 'githubcom'
    assert vs.extract_domain('http://github.com:443/x?y=1') == 'githubcom'


# ---------- 大小写不敏感（核心诉求）----------
def test_case_insensitive_match():
    """用 github 能搜到 GitHub，反之亦然。"""
    row = {'name': 'GitHub', 'url': 'https://github.com', 'aliases': []}
    assert vs.score('github', row) > 0
    assert vs.score('GitHub', row) > 0
    assert vs.score('GITHUB', row) > 0


# ---------- 部分匹配 ----------
def test_partial_prefix_match():
    """打半截也能命中（前缀）。"""
    row = {'name': 'GitHub', 'url': '', 'aliases': []}
    assert vs.score('git', row) > 0
    assert vs.score('gitH', row) > 0


def test_complete_match_beats_partial():
    """完全相等应比前缀/子串得分高，保证精确项排前。"""
    exact = {'name': 'github', 'url': '', 'aliases': []}
    partial = {'name': 'github-enterprise', 'url': '', 'aliases': []}
    assert vs.score('github', exact) > vs.score('github', partial)


# ---------- 多字段 & 别名 ----------
def test_url_domain_match():
    """名称不含关键词，但网址域名含也能命中。"""
    row = {'name': '代码托管', 'url': 'https://gitlab.com', 'aliases': []}
    assert vs.score('gitlab', row) > 0


def test_alias_match():
    """别名命中：给 GitHub 挂 gh 别名。"""
    row = {'name': 'GitHub', 'url': '', 'aliases': ['gh', 'github.com']}
    assert vs.score('gh', row) > 0


def test_no_match_returns_zero():
    """完全无关的查询不打分。"""
    row = {'name': 'GitHub', 'url': 'https://github.com', 'aliases': []}
    assert vs.score('weibo', row) == 0.0


# ---------- 排序 ----------
def test_search_orders_by_score():
    """search 按分数降序，精确项在最前。"""
    rows = [
        {'id': 1, 'name': 'GitHub Enterprise', 'url': '', 'aliases': []},
        {'id': 2, 'name': 'GitHub', 'url': '', 'aliases': []},
        {'id': 3, 'name': 'Gmail', 'url': '', 'aliases': []},
    ]
    got = vs.search('github', rows)
    assert [r['id'] for r in got] == [2, 1]
    # 无关项被过滤
    assert all(r['id'] != 3 for r in got)


def test_search_empty_query():
    """空查询不命中任何项（由调用方决定是否展示全部）。"""
    rows = [{'id': 1, 'name': 'GitHub', 'url': '', 'aliases': []}]
    assert vs.search('', rows) == []


def test_search_limit():
    """limit 生效。"""
    rows = [{'id': i, 'name': f'git{i}', 'url': '', 'aliases': []}
            for i in range(10)]
    assert len(vs.search('git', rows, limit=3)) == 3
