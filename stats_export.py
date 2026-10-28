"""稳定 JSON 出口：把统计结果写成 `app_stats.json`，供 AI 直接读取。

设计取舍：
- AI 不该去解析 SQLite，也不该猜表结构。这里提供一个结构固定、
  自描述的文件，AI 读它就能回答「今天时间花在哪」这类问题。
- 每次写都是**全量覆盖**，不做增量，避免文件状态不一致。
- 结构里同时给 exe（机器可追溯）、name（人可读）、category（语义分类），
  以及 count / seconds 两个正交维度。

文件结构（date 均为 YYYY-MM-DD）：

    {
      "generated_at": "2026-10-27T23:40:00+08:00",
      "today": {
        "date": "2026-10-27",
        "total_count": 9640,
        "total_seconds": 24000,
        "apps": [
          {"exe": "code.exe", "name": "VS Code", "category": "dev",
           "count": 4120, "seconds": 6800,
           "count_share": 0.427, "seconds_share": 0.283}
        ]
      },
      "recent": {
        "days": 7,
        "from": "2026-10-21",
        "to": "2026-10-27",
        "apps": [ ... 同上结构，count/seconds 为区间内总和 ... ]
      }
    }
"""
import json
import os
from datetime import datetime, timedelta

import db
from app_aliases import resolve
from config import BASE_DIR
from logger import logger

EXPORT_PATH = os.path.join(BASE_DIR, 'app_stats.json')
RECENT_DAYS = 7


def _pct(part, total):
    """占比，保留三位小数；total 为 0 时返回 0.0。"""
    if not total:
        return 0.0
    return round(part / total, 3)


def _date_list(end_str, days):
    """返回 [start_date, end_date]，闭区间，共 days 天。"""
    end = datetime.strptime(end_str, '%Y-%m-%d')
    start = end - timedelta(days=max(days - 1, 0))
    return start.strftime('%Y-%m-%d'), end_str


def _app_rows(pairs, aliases=None):
    """把 [(exe, count, seconds)] 渲染成带 name/category/占比的条目。"""
    total_count = sum(c for _, c, _ in pairs)
    total_seconds = sum(s for _, _, s in pairs)
    rows = []
    for exe, count, seconds in pairs:
        info = resolve(exe, aliases)
        rows.append({
            'exe': info['exe'],
            'name': info['name'],
            'category': info['category'],
            'count': int(count),
            'seconds': int(seconds),
            'count_share': _pct(count, total_count),
            'seconds_share': _pct(seconds, total_seconds),
        })
    return rows, int(total_count), int(total_seconds)


def build_snapshot(today=None, live_today=None, days=RECENT_DAYS, aliases=None):
    """构造导出用的字典（纯函数，便于测试）。

    live_today: {exe: {'count': n, 'seconds': n}}，来自内存 tracker。
    传入时会覆盖数据库里今天的值——因为周期落库有 20 秒延迟，
    直接用内存值更准。
    """
    today = today or datetime.now().strftime('%Y-%m-%d')
    start, end = _date_list(today, days)

    # 今天
    today_map = dict(db.get_app_stats(today))
    if live_today:
        for exe, v in live_today.items():
            today_map[exe] = {'count': int(v.get('count', 0)),
                              'seconds': int(v.get('seconds', 0))}
    today_pairs = sorted(
        ((exe, v['count'], v['seconds']) for exe, v in today_map.items()),
        key=lambda x: (x[1], x[2]), reverse=True,
    )
    today_rows, today_count, today_seconds = _app_rows(today_pairs, aliases)

    # 近 N 天：用聚合查询（GROUP BY app + SUM），不是联表
    recent_pairs = db.get_app_aggregate(start, end, order_by='count')
    recent_rows, recent_count, recent_seconds = _app_rows(recent_pairs, aliases)

    return {
        'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'today': {
            'date': today,
            'total_count': today_count,
            'total_seconds': today_seconds,
            'apps': today_rows,
        },
        'recent': {
            'days': days,
            'from': start,
            'to': end,
            'total_count': recent_count,
            'total_seconds': recent_seconds,
            'apps': recent_rows,
        },
    }


def write_json(path=EXPORT_PATH, live_today=None, days=RECENT_DAYS):
    """生成并写入 app_stats.json，返回文件路径；失败返回 None。

    写文件失败不抛异常——统计导出是附加能力，不能影响桌宠主流程。
    """
    try:
        snapshot = build_snapshot(live_today=live_today, days=days)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)      # 原子替换，避免读到写了一半的文件
        return path
    except Exception:
        logger.exception('统计 JSON 导出失败')
        return None
