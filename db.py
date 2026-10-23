"""SQLite 数据层：按天聚合成 daily_stats 表 + 按键明细表 daily_key_stats。"""
import sqlite3
from collections import defaultdict
from datetime import datetime
from config import DB_PATH


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        'CREATE TABLE IF NOT EXISTS daily_stats ('
        'date TEXT PRIMARY KEY,'
        'count INTEGER NOT NULL'
        ')'
    )
    # 按键明细表：每个键每天被按多少次。
    # 冠军键（MVP）和热力图都从这张表查询，天然支持多键并列。
    conn.execute(
        'CREATE TABLE IF NOT EXISTS daily_key_stats ('
        'date TEXT NOT NULL,'
        'key TEXT NOT NULL,'
        'count INTEGER NOT NULL,'
        'PRIMARY KEY (date, key)'
        ')'
    )
    # 轻量键值状态表：存跨重启的运行状态（如天气播报的「已弹过/已确认」日期）。
    conn.execute(
        'CREATE TABLE IF NOT EXISTS app_state ('
        'key TEXT PRIMARY KEY,'
        'value TEXT NOT NULL'
        ')'
    )
    conn.commit()
    return conn


def get_state(key, default=None):
    """读取 app_state 表中的某个键；不存在返回 default。"""
    conn = _connect()
    row = conn.execute(
        'SELECT value FROM app_state WHERE key = ?', (key,)
    ).fetchone()
    conn.close()
    return row[0] if row else default


def set_state(key, value):
    """写入 app_state 表（upsert）。value 转成字符串保存。"""
    conn = _connect()
    conn.execute(
        'INSERT INTO app_state(key, value) VALUES(?, ?) '
        'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def save_count(date_str, count):
    """写入某一天的总次数（按天更新，不存在则插入）。"""
    conn = _connect()
    conn.execute(
        'INSERT INTO daily_stats(date, count) VALUES(?, ?) '
        'ON CONFLICT(date) DO UPDATE SET count = excluded.count',
        (date_str, int(count)),
    )
    conn.commit()
    conn.close()


def get_count(date_str):
    """读取某一天的总次数，没有则返回 0。"""
    conn = _connect()
    row = conn.execute(
        'SELECT count FROM daily_stats WHERE date = ?', (date_str,)
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def save_key_counts(date_str, key_counts):
    """批量写入某天各键的计数。key_counts 形如 {'e': 612, 'space': 720}。"""
    conn = _connect()
    for key, cnt in key_counts.items():
        conn.execute(
            'INSERT INTO daily_key_stats(date, key, count) VALUES(?, ?, ?) '
            'ON CONFLICT(date, key) DO UPDATE SET count = excluded.count',
            (date_str, str(key), int(cnt)),
        )
    conn.commit()
    conn.close()


def get_key_counts(date_str):
    """读取某天各键计数，返回 {key: count}；当天重启时用于恢复内存计数。"""
    conn = _connect()
    rows = conn.execute(
        'SELECT key, count FROM daily_key_stats WHERE date = ?', (date_str,)
    ).fetchall()
    conn.close()
    return {k: c for k, c in rows}


def _is_letter_key(key):
    """判断是否为 26 个英文字母键（单个 a-z / A-Z 字母）。

    MVP 冠军键只从英文字母里选，因此空格、回车、修饰键等特殊键
    不再参与冠军角逐。
    """
    return (len(key) == 1
            and (('a' <= key <= 'z') or ('A' <= key <= 'Z')))


def get_top_keys(date_str):
    """查某天冠军键（支持多键并列），返回 [(key, count)]，按出现顺序。

    冠军键仅从 26 个英文字母键里选出；当天没有字母键时返回空列表。
    """
    conn = _connect()
    rows = conn.execute(
        'SELECT key, count FROM daily_key_stats WHERE date = ?', (date_str,)
    ).fetchall()
    conn.close()
    letter_rows = [(k, c) for k, c in rows if _is_letter_key(k)]
    if not letter_rows:
        return []
    maxc = max(c for _, c in letter_rows)
    return [(k, c) for k, c in letter_rows if c == maxc]


def get_daily_mvp(days=None):
    """返回 [(date, count, mvp_label)]，mvp_label 形如 'e ×612' 或 'a 等2键 ×540'。

    冠军键仅从 26 个英文字母键里选出。
    以 daily_stats（日期+次数）为主表，保证历史数据不丢；
    再从 daily_key_stats 查该天字母冠军键，拼成「键 ×次数」字符串。
    盲盒：今天的行（尚未封存）MVP 显示「?」，不揭露实时写入的键；
    历史行显示真实冠军；无明细且非今天才显示 '-'。
    days=None 表示全部历史，否则返回最近 n 天。
    供历史表格展示「日期 | 次数 | MVP键」。
    """
    conn = _connect()
    if days is None:
        rows = conn.execute(
            'SELECT date, count FROM daily_stats ORDER BY date DESC'
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT date, count FROM daily_stats ORDER BY date DESC LIMIT ?',
            (days,),
        ).fetchall()
    key_rows = conn.execute(
        'SELECT date, key, count FROM daily_key_stats'
    ).fetchall()
    conn.close()

    by_date = defaultdict(dict)
    for d, k, c in key_rows:
        by_date[d][k] = c

    today = datetime.now().strftime('%Y-%m-%d')
    result = []
    for dt, cnt in rows:
        if dt == today:
            # 盲盒：当天尚未封存，不揭露真实冠军
            label = '?'
        else:
            dc = by_date.get(dt, {})
            # 冠军键仅从 26 个英文字母里选
            letter_dc = {k: c for k, c in dc.items() if _is_letter_key(k)}
            if letter_dc:
                maxc = max(letter_dc.values())
                tops = [k for k, c in letter_dc.items() if c == maxc]
                label = f'{tops[0]} ×{maxc}'
                if len(tops) > 1:
                    label = f'{tops[0]} 等{len(tops)}键 ×{maxc}'
            else:
                label = '-'
        result.append((dt, cnt, label))
    return result
