#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy 积分台账数据层（纯本地读取，不联网、不调用任何 AI）。

数据来源优先级：
  1. WorkBuddy 本地库 ~/.workbuddy/workbuddy.db 的 session_usage 表
     （credit_json 是 {调用ID: 积分}，求和即该会话消耗）
  2. 读不到数据库时，退回已有的台账 CSV（credit_summary.csv）

为什么要先复制到临时目录：
  WorkBuddy 运行时是 WAL 模式，-wal 里可能有还没落盘的数据。
  直接打开原库可能被锁、或只读到一半。复制 db + -wal + -shm 到临时目录
  再打开，既拿到最新数据，也完全不碰原文件（只读、无副作用）。

对外只暴露 load_overview()，永不抛异常：出错时返回 ok=False 的空结构，
界面照常显示「暂无数据」，不会让桌宠崩掉。
"""
import csv
import json
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

from logger import logger

HOME = Path.home()
WB_DB = HOME / '.workbuddy' / 'workbuddy.db'
LEDGER_DIR = HOME / 'WorkBuddy' / 'credit-ledger'
SUMMARY_CSV = LEDGER_DIR / 'credit_summary.csv'

CACHE_TTL = 20.0            # 秒。频繁点开卡片时不必每次重新拷贝数据库
_cache = {'ts': 0.0, 'data': None}


# ============================================================
# 基础解析
# ============================================================
def _parse_credits(raw):
    """credit_json → 该会话总积分。格式异常一律当 0，不抛异常。"""
    if not raw:
        return 0.0
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return 0.0
    if isinstance(data, dict):
        values = data.values()
    elif isinstance(data, (list, tuple)):
        values = data
    else:
        return 0.0
    total = 0.0
    for v in values:
        try:
            total += float(v)
        except (TypeError, ValueError):
            continue
    return total


def _ms_to_epoch_ms(ms):
    """毫秒时间戳 → 毫秒（兼容秒级时间戳）；无效值返回 None。"""
    try:
        ms = float(ms)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    if ms < 1e11:              # 秒级
        ms = ms * 1000.0
    return ms


def _ms_to_date(ms):
    """毫秒时间戳 → 'YYYY-MM-DD'，兼容秒级时间戳。"""
    epoch_ms = _ms_to_epoch_ms(ms)
    if epoch_ms is None:
        return None
    try:
        return datetime.fromtimestamp(epoch_ms / 1000.0).strftime('%Y-%m-%d')
    except (OverflowError, OSError, ValueError):
        return None


def _date_range(end, days):
    return [(end - timedelta(days=days - 1 - i)).strftime('%Y-%m-%d')
            for i in range(days)]


# ============================================================
# 数据来源
# ============================================================
def _rows_from_db():
    """返回 [(date, credits)]；读不到返回 None。"""
    if not WB_DB.exists():
        return None

    tmpdir = Path(tempfile.mkdtemp(prefix='pet_credit_'))
    try:
        for name in (WB_DB.name, WB_DB.name + '-wal', WB_DB.name + '-shm'):
            src = WB_DB.with_name(name)
            if src.exists():
                try:
                    shutil.copy2(src, tmpdir / name)
                except OSError:
                    pass        # 单个附属文件拷不到不影响主库
        target = tmpdir / WB_DB.name
        if not target.exists():
            return None

        conn = sqlite3.connect(str(target), timeout=3)
        conn.row_factory = sqlite3.Row
        try:
            rows = _query(conn)
        finally:
            conn.close()
        return rows
    except Exception:
        logger.exception('读取 WorkBuddy 积分库失败')
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _query(conn):
    """优先带会话标题/时间的完整查询，表结构变了就退到最小查询。"""
    full_sql = """
        SELECT u.session_id  AS sid,
               u.credit_json AS cj,
               u.updated_at  AS u_upd,
               s.last_activity_at AS last_act,
               s.created_at  AS created,
               s.updated_at  AS s_upd
        FROM session_usage u
        LEFT JOIN sessions s ON s.id = u.session_id
    """
    try:
        cur = conn.execute(full_sql)
        fetched = cur.fetchall()
    except sqlite3.Error:
        # 例如 sessions 表改名 / 少了 last_activity_at 列
        logger.warning('积分库完整查询失败，退回最小字段查询', exc_info=True)
        cur = conn.execute(
            'SELECT session_id AS sid, credit_json AS cj, updated_at AS u_upd '
            'FROM session_usage')
        fetched = cur.fetchall()

    out = []
    for r in fetched:
        date = None
        for key in ('last_act', 's_upd', 'created', 'u_upd'):
            try:
                date = _ms_to_date(r[key])
            except (IndexError, KeyError):
                date = None
            if date:
                break
        if date:
            out.append((date, _parse_credits(r['cj'])))
    return out


def _rows_from_csv():
    """退回台账 CSV：date,sessions,credits,cumulative_credits。"""
    if not SUMMARY_CSV.exists():
        return None
    rows = []
    try:
        with open(SUMMARY_CSV, encoding='utf-8-sig', newline='') as f:
            for row in csv.DictReader(f):
                date = (row.get('date') or '').strip()
                if not date:
                    continue
                try:
                    rows.append((date, float(row.get('credits') or 0)))
                except (TypeError, ValueError):
                    continue
    except OSError:
        logger.exception('读取积分台账 CSV 失败')
        return None
    return rows or None


# ============================================================
# 对外接口
# ============================================================
def _empty(days=14):
    today = datetime.now().strftime('%Y-%m-%d')
    series = [(d, 0.0, False) for d in _date_range(
        datetime.now(), days)]
    return {
        'ok': False,
        'source': 'none',
        'today': today,
        'today_credits': 0.0,
        'today_sessions': 0,
        'total_credits': 0.0,
        'total_sessions': 0,
        'month_credits': 0.0,
        'series': series,
        'day_sessions': {},
        'first_date': None,
    }


def load_overview(days=14, force=False):
    """汇总积分数据。

    返回 dict：
      ok / source('db'|'csv'|'none')
      today, today_credits, today_sessions
      total_credits, total_sessions, month_credits
      series  [(date, credits, has_data)]  最近 days 天，缺数据 has_data=False
      day_sessions  {date: 当天会话数}（悬停卡片用）
      first_date  台账最早一天（'YYYY-MM-DD'）
    """
    now = time.time()
    if (not force and _cache['data'] is not None
            and now - _cache['ts'] < CACHE_TTL):
        return _cache['data']

    try:
        rows = _rows_from_db()
        source = 'db'
        if not rows:
            rows = _rows_from_csv()
            source = 'csv' if rows else 'none'
        if not rows:
            data = _empty(days)
            _cache.update(ts=now, data=data)
            return data

        per_day = {}
        per_day_sessions = {}
        for date, credits in rows:
            per_day[date] = per_day.get(date, 0.0) + credits
            per_day_sessions[date] = per_day_sessions.get(date, 0) + 1

        today_obj = datetime.now()
        today = today_obj.strftime('%Y-%m-%d')
        month_prefix = today[:7]

        total_credits = sum(per_day.values())
        series = []
        for d in _date_range(today_obj, days):
            has = d in per_day
            series.append((d, per_day.get(d, 0.0), has))

        data = {
            'ok': True,
            'source': source,
            'today': today,
            'today_credits': per_day.get(today, 0.0),
            'today_sessions': per_day_sessions.get(today, 0),
            'total_credits': total_credits,
            'total_sessions': len(rows),
            'month_credits': sum(v for d, v in per_day.items()
                                 if d.startswith(month_prefix)),
            'series': series,
            'day_sessions': per_day_sessions,
            'first_date': min(per_day),
        }
        _cache.update(ts=now, data=data)
        return data
    except Exception:
        logger.exception('汇总积分数据失败')
        return _empty(days)
