"""密码本数据层（SQLite，与项目其它数据同库）。

沿用 db.py / db_todo.py 的风格：同一个 DB_PATH、可重复打开、
schema 用 CREATE TABLE IF NOT EXISTS 幂等创建。

表结构：
    vault_accounts (
        id           自增主键
        name         条目名（如 'GitHub'），搜索主字段
        url          网址（域名参与搜索）
        username     账号名
        password_enc 密码密文（DPAPI，见 vault_crypto；**绝不存明文**）
        aliases      别名，逗号分隔字符串（如 'gh,github.com'），参与搜索
        note         备注，参与搜索（低权重）
        created_at   创建时间
        updated_at   更新时间
    )

安全约定：
- 本模块只管存取，**不**负责加解密；密文由 vault_crypto 生成/解析。
- 任何异常/日志都不得回显 password_enc 或明文。

返回给上层的记录是 dict（供 vault_search 直接打分），
其中 aliases 已拆成 list。
"""
import sqlite3
from datetime import datetime

from config import DB_PATH


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        'CREATE TABLE IF NOT EXISTS vault_accounts ('
        'id INTEGER PRIMARY KEY AUTOINCREMENT,'
        'name TEXT NOT NULL,'
        'url TEXT,'
        'username TEXT,'
        'password_enc TEXT NOT NULL,'
        'aliases TEXT,'
        'note TEXT,'
        "created_at TEXT DEFAULT (datetime('now','localtime')),"
        "updated_at TEXT DEFAULT (datetime('now','localtime'))"
        ')'
    )
    conn.commit()
    return conn


def _now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _row_to_dict(row):
    """DB 行 → 供搜索/UI 使用的 dict（aliases 拆成 list）。"""
    (rid, name, url, username, password_enc,
     aliases, note) = row
    alias_list = [a.strip() for a in (aliases or '').split(',') if a.strip()]
    return {
        'id': rid,
        'name': name or '',
        'url': url or '',
        'username': username or '',
        'password_enc': password_enc or '',
        'aliases': alias_list,
        'note': note or '',
    }


def add_account(name, password_enc, url='', username='', aliases='', note=''):
    """新增一条账号，返回新行 id。

    password_enc 必须是 vault_crypto.encrypt() 的结果（密文）；
    这里不做校验，但要确保调用方绝不传明文。
    aliases 传逗号分隔字符串。
    """
    conn = _connect()
    cur = conn.execute(
        'INSERT INTO vault_accounts'
        '(name, url, username, password_enc, aliases, note)'
        'VALUES(?, ?, ?, ?, ?, ?)',
        (name.strip(), url.strip(), username.strip(),
         password_enc, aliases.strip(), note.strip()),
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return new_id


def update_account(account_id, name=None, url=None, username=None,
                   password_enc=None, aliases=None, note=None):
    """更新一条账号的字段；password_enc 传 None 表示不改密码。

    未传入（None）的字段保持原值。返回是否更新成功。
    """
    fields = []
    values = []
    for col, val in (
        ('name', name), ('url', url), ('username', username),
        ('password_enc', password_enc), ('aliases', aliases),
        ('note', note),
    ):
        if val is not None:
            fields.append(f'{col}=?')
            values.append(val.strip() if isinstance(val, str) else val)
    if not fields:
        return False
    fields.append('updated_at=?')
    values.append(_now_str())
    values.append(account_id)
    conn = _connect()
    cur = conn.execute(
        f'UPDATE vault_accounts SET {", ".join(fields)} WHERE id=?',
        values,
    )
    conn.commit()
    changed = cur.rowcount
    conn.close()
    return changed > 0


def delete_account(account_id):
    """删除一条账号。"""
    conn = _connect()
    conn.execute('DELETE FROM vault_accounts WHERE id=?', (account_id,))
    conn.commit()
    conn.close()


def get_account(account_id):
    """按 id 取一条，返回 dict；不存在返回 None。"""
    conn = _connect()
    row = conn.execute(
        'SELECT id, name, url, username, password_enc, aliases, note '
        'FROM vault_accounts WHERE id=?',
        (account_id,),
    ).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def list_accounts():
    """取全部账号（供模糊搜索用），按名称升序。

    返回 dict 列表；除「查询窗口」外不要把它直接铺到界面，
    因为 password_enc 会一并带出（虽然只是密文）。
    """
    conn = _connect()
    rows = conn.execute(
        'SELECT id, name, url, username, password_enc, aliases, note '
        'FROM vault_accounts ORDER BY name COLLATE NOCASE ASC'
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def count_accounts():
    """条目总数（用于菜单/空态判断）。"""
    conn = _connect()
    row = conn.execute('SELECT COUNT(*) FROM vault_accounts').fetchone()
    conn.close()
    return row[0] if row else 0


def name_exists(name, exclude_id=None):
    """是否已存在同名条目（去重提示用，非强约束）。"""
    conn = _connect()
    if exclude_id is None:
        row = conn.execute(
            'SELECT 1 FROM vault_accounts WHERE name=? LIMIT 1',
            (name.strip(),),
        ).fetchone()
    else:
        row = conn.execute(
            'SELECT 1 FROM vault_accounts WHERE name=? AND id<>? LIMIT 1',
            (name.strip(), exclude_id),
        ).fetchone()
    conn.close()
    return row is not None
