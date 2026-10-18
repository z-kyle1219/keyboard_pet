"""待办日程 SQLite 数据层。

遵循项目现有 db.py 的 SQLite 风格：均以 TEXT 存储日期/时间、可重复打开、
跨天不迁移数据（靠查询时过滤）。

表结构（定稿）：
    todo (
        id         自增主键，勾选/编辑/删除用
        title      待办标题
        due_at     截止时间 'YYYY-MM-DD HH:MM'，排序键
        done       0 未完成 / 1 已完成
        done_at    完成时刻 'YYYY-MM-DD HH:MM:SS'，勾掉留一天用
        created_at 创建时间（调试用）
    )

业务规则（用户定稿）：
- 勾掉（done=1）只留一天：靠 done_at 属于当天判断，第二天自动隐藏。
- 没做的（done=0）轮换到下一天：due_at 不随日期变化，第二天查询自然还在。
- 排序：按 due_at 升序。
- 不要优先级、不要完成率/近7天统计。
"""
import sqlite3
from datetime import datetime

from config import DB_PATH


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        'CREATE TABLE IF NOT EXISTS todo ('
        'id INTEGER PRIMARY KEY AUTOINCREMENT,'
        'title TEXT NOT NULL,'
        "due_at TEXT NOT NULL,"
        'done INTEGER NOT NULL DEFAULT 0,'
        'done_at TEXT,'
        "created_at TEXT DEFAULT (datetime('now','localtime'))"
        ')'
    )
    conn.execute(
        'CREATE INDEX IF NOT EXISTS idx_todo_due_at ON todo(due_at)'
    )
    conn.commit()
    return conn


def _now_str():
    """当前本地时间，格式 'YYYY-MM-DD HH:MM'（表内其余时间大多精确到分钟）。"""
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def format_due(due_at):
    """把 'YYYY-MM-DD HH:MM' 转成汉字展示：'2026年10月19日 14时00分'。

    用于界面上第三列完整日期时间的展示。对无法解析的值做兜底，
    直接返回原串，避免 UI 崩溃。
    """
    if not due_at:
        return ''
    try:
        dt = datetime.strptime(due_at, '%Y-%m-%d %H:%M')
    except Exception:
        return due_at
    return (f'{dt.year}年{dt.month}月{dt.day}日 '
            f'{dt.hour:02d}时{dt.minute:02d}分')


def add_todo(title, due_at):
    """新增一条待办，返回新行 id。

    due_at 传入 'YYYY-MM-DD HH:MM'；对空值兜底为「当天最后时刻」，
    确保排序时始终能落在当天的末尾。
    """
    conn = _connect()
    cur = conn.execute(
        'INSERT INTO todo(title, due_at) VALUES(?, ?)',
        (title.strip(), due_at),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def set_done(task_id, done):
    """勾选/取消勾选一条待办。

    done=True 时写入 done_at（完成时刻）；取消勾选时清空 done_at。
    """
    conn = _connect()
    if done:
        conn.execute(
            'UPDATE todo SET done=1, done_at=? WHERE id=?',
            (_now_str(), task_id),
        )
    else:
        conn.execute(
            'UPDATE todo SET done=0, done_at=NULL WHERE id=?',
            (task_id,),
        )
    conn.commit()
    conn.close()


def delete_todo(task_id):
    """删除一条待办。"""
    conn = _connect()
    conn.execute('DELETE FROM todo WHERE id=?', (task_id,))
    conn.commit()
    conn.close()


def get_today_todos():
    """查询「今日该展示」的待办列表，按截止时间升序。

    规则：
    - 未完成（done=0）：不管哪天，只要还没做就轮换到今天，全部展示。
    - 已完成（done=1）：只留当天完成的（done_at 属于今天），
      昨天及更早完成的自动隐藏（「勾掉留一天」）。
    返回 [(id, title, due_at, done, done_at), ...]。
    """
    today = datetime.now().strftime('%Y-%m-%d')
    conn = _connect()
    rows = conn.execute(
        'SELECT id, title, due_at, done, done_at FROM todo '
        "WHERE done=0 OR done_at LIKE ? "
        'ORDER BY due_at ASC, id ASC',
        (today + '%',),
    ).fetchall()
    conn.close()
    return rows


def get_pending_count():
    """未完成待办数量（用于角标「N 待办」）。"""
    conn = _connect()
    row = conn.execute(
        'SELECT COUNT(*) FROM todo WHERE done=0'
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def has_urgent_pending():
    """是否即将临期（角标由粉转红的依据）。

    定义（用户定稿）：若存在一条未完成待办，其截止时间距现在
    <= 12 小时（「临近截止半天」），则返回 True。
    """
    conn = _connect()
    rows = conn.execute(
        'SELECT due_at FROM todo WHERE done=0'
    ).fetchall()
    conn.close()
    if not rows:
        return False
    now = datetime.now()
    for (due_at,) in rows:
        try:
            due = datetime.strptime(due_at, '%Y-%m-%d %H:%M')
        except Exception:
            continue
        # 已过期的未完成待办也算紧急
        if due <= now:
            return True
        if (due - now).total_seconds() <= 12 * 3600:
            return True
    return False


def get_all_todos():
    """查询全部待办（含完成态），按截止时间升序（近→远）。

    用于列表第三列按日期排序展示。
    返回 [(id, title, due_at, done, done_at), ...]。
    """
    conn = _connect()
    rows = conn.execute(
        'SELECT id, title, due_at, done, done_at FROM todo '
        'ORDER BY due_at ASC, id ASC'
    ).fetchall()
    conn.close()
    return rows


def get_due_stats():
    """按截止日期统计，返回 {'today': n, 'overdue': n, 'future': n}。

    - today    今天截止（due_at 日期段 == 今天）
    - overdue  已过期（due_at < 现在）
    - future   未来截止（due_at 日期段 > 今天）
    均基于未完成（done=0）的待办统计。
    """
    today = datetime.now().strftime('%Y-%m-%d')
    now = datetime.now()
    today_n = overdue_n = future_n = 0
    for (due_at,) in _pending_due_ats():
        try:
            due = datetime.strptime(due_at, '%Y-%m-%d %H:%M')
        except Exception:
            continue
        if due < now:
            overdue_n += 1
        elif due_at[:10] == today:
            today_n += 1
        else:
            future_n += 1
    return {'today': today_n, 'overdue': overdue_n, 'future': future_n}


def _pending_due_ats():
    """取未完成待办的 due_at 列表（供统计用）。"""
    conn = _connect()
    rows = conn.execute(
        'SELECT due_at FROM todo WHERE done=0'
    ).fetchall()
    conn.close()
    return rows
