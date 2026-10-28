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
    # 按应用明细表：某天某个 exe 被敲了多少键、作为前台窗口待了多少秒。
    # 复合主键 (date, app) —— 一行是「某天某应用的一格统计」，天然防重复；
    # 时间范围（近 7 天等）一律用 GROUP BY 现算，不另建汇总表。
    conn.execute(
        'CREATE TABLE IF NOT EXISTS daily_app_stats ('
        'date TEXT NOT NULL,'
        'app TEXT NOT NULL,'
        'count INTEGER NOT NULL DEFAULT 0,'
        'seconds INTEGER NOT NULL DEFAULT 0,'
        'PRIMARY KEY (date, app)'
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


def save_app_stats(date_str, app_counts, app_seconds=None):
    """批量写入某天各应用的次数与秒数（upsert）。

    app_counts 形如 {'chrome.exe': 4120}；app_seconds 形如 {'chrome.exe': 6800}。
    两张字典的 key 取并集写入，所以「只敲了键」或「只停留没敲键」的应用
    都会留下记录，不会互相覆盖。
    """
    app_seconds = app_seconds or {}
    apps = set(app_counts) | set(app_seconds)
    if not apps:
        return
    conn = _connect()
    for app in apps:
        conn.execute(
            'INSERT INTO daily_app_stats(date, app, count, seconds) '
            'VALUES(?, ?, ?, ?) '
            'ON CONFLICT(date, app) DO UPDATE SET '
            'count = excluded.count, seconds = excluded.seconds',
            (date_str, str(app),
             int(app_counts.get(app, 0)),
             int(app_seconds.get(app, 0))),
        )
    conn.commit()
    conn.close()


def get_app_stats(date_str):
    """读取某天各应用统计，返回 {app: {'count': n, 'seconds': n}}。"""
    conn = _connect()
    rows = conn.execute(
        'SELECT app, count, seconds FROM daily_app_stats WHERE date = ?',
        (date_str,),
    ).fetchall()
    conn.close()
    return {a: {'count': c, 'seconds': s} for a, c, s in rows}


def get_app_aggregate(since_date, until_date=None, order_by='count'):
    """按应用聚合某日期区间，返回 [(app, count, seconds)]。

    这是「聚合」而不是「联表」：对象始终是 daily_app_stats 一张表，
    GROUP BY app 把同一应用多天的行压成一行，SUM 求和。
    「近 7 天」「近 30 天」只是换一个 since_date，不需要新建表。

    order_by: 'count'（默认，敲键量）或 'seconds'（停留时长）。
    """
    col = 'SUM(seconds)' if order_by == 'seconds' else 'SUM(count)'
    sql = ('SELECT app, SUM(count), SUM(seconds) FROM daily_app_stats '
           'WHERE date >= ?')
    params = [since_date]
    if until_date:
        sql += ' AND date <= ?'
        params.append(until_date)
    sql += ' GROUP BY app ORDER BY ' + col + ' DESC'
    conn = _connect()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [(a, int(c or 0), int(s or 0)) for a, c, s in rows]


def get_app_daily(since_date, until_date=None):
    """按「天 × 应用」读取明细，返回 {(app, date): (count, seconds)}。

    供折线图按天取点使用。这里是明细而非聚合——折线的横轴就是日期，
    每个点对应一天，正好是最细的粒度。
    """
    sql = 'SELECT date, app, count, seconds FROM daily_app_stats WHERE date >= ?'
    params = [since_date]
    if until_date:
        sql += ' AND date <= ?'
        params.append(until_date)
    conn = _connect()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return {(a, d): (int(c or 0), int(s or 0)) for d, a, c, s in rows}


def get_app_total(date_str):
    """某天所有应用敲键次数之和（用于校验与 daily_stats 是否一致）。"""
    conn = _connect()
    row = conn.execute(
        'SELECT SUM(count) FROM daily_app_stats WHERE date = ?', (date_str,)
    ).fetchone()
    conn.close()
    return int(row[0] or 0) if row else 0


def clear_idle_seconds(apps):
    """把这些应用的「停留秒数」全部清零（保留次数），返回受影响行数。

    锁屏类进程代表「人不在电脑前」，那段时间不该算进使用时长。
    但历史数据可能已经写进去了，只改未来的采样挡不住旧值——
    所以启动时跑一次尽数抹平。次数不清，否则总数与明细会对不上。
    """
    apps = [str(a) for a in apps]
    if not apps:
        return 0
    placeholders = ','.join('?' * len(apps))
    conn = _connect()
    cur = conn.execute(
        'UPDATE daily_app_stats SET seconds = 0 '
        'WHERE seconds != 0 AND app IN (' + placeholders + ')',
        apps,
    )
    changed = cur.rowcount
    conn.commit()
    conn.close()
    return changed


def get_daily_mvp():
    """返回全部历史 [(date, count, mvp_label)]，按日期倒序（最近的在最前）。

    mvp_label 形如 'e ×612' 或 'a 等2键 ×540'。
    冠军键仅从 26 个英文字母键里选出。
    以 daily_stats（日期+次数）为主表，保证历史数据不丢；
    再从 daily_key_stats 查该天字母冠军键，拼成「键 ×次数」字符串。
    盲盒：今天的行（尚未封存）MVP 显示「?」，不揭露实时写入的键；
    历史行显示真实冠军；无明细且非今天才显示 '-'。
    供历史表格展示「日期 | 次数 | MVP键」。
    """
    conn = _connect()
    rows = conn.execute(
        'SELECT date, count FROM daily_stats ORDER BY date DESC'
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
