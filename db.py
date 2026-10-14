"""SQLite 数据层：按天聚合成 daily_stats 表。"""
import sqlite3
from config import DB_PATH


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        'CREATE TABLE IF NOT EXISTS daily_stats ('
        'date TEXT PRIMARY KEY,'
        'count INTEGER NOT NULL'
        ')'
    )
    conn.commit()
    return conn


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


def get_recent_days(n=7):
    """返回最近 n 天的记录，按日期倒序（最新在前）。"""
    conn = _connect()
    rows = conn.execute(
        'SELECT date, count FROM daily_stats '
        'ORDER BY date DESC LIMIT ?', (n,)
    ).fetchall()
    conn.close()
    return rows


def get_all_days():
    """返回全部历史记录，按日期倒序（最新在前）。"""
    conn = _connect()
    rows = conn.execute(
        'SELECT date, count FROM daily_stats '
        'ORDER BY date DESC'
    ).fetchall()
    conn.close()
    return rows
