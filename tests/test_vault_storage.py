"""db_vault 数据层与 vault_crypto 加密层的单元测试。

运行：uv run pytest

注意：
- db_vault 测试通过 monkeypatch 把 DB_PATH 指向临时文件，绝不碰真实库。
- vault_crypto 依赖 Windows DPAPI，非 Windows 自动跳过。
"""
import sys

import pytest

import db_vault
import vault_crypto


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """把 db_vault 的库指向临时文件，保证测试隔离。"""
    monkeypatch.setattr(db_vault, 'DB_PATH', str(tmp_path / 'vault_test.db'))
    return db_vault


# ---------- 数据层 ----------
def test_add_and_get(temp_db):
    rid = temp_db.add_account('GitHub', 'ENC', url='https://github.com',
                              username='kyle', aliases='gh,github.com')
    rec = temp_db.get_account(rid)
    assert rec['name'] == 'GitHub'
    assert rec['username'] == 'kyle'
    assert rec['aliases'] == ['gh', 'github.com']
    assert rec['password_enc'] == 'ENC'


def test_list_and_count(temp_db):
    temp_db.add_account('A', 'e1')
    temp_db.add_account('B', 'e2')
    assert temp_db.count_accounts() == 2
    assert {r['name'] for r in temp_db.list_accounts()} == {'A', 'B'}


def test_update_keeps_password_when_none(temp_db):
    rid = temp_db.add_account('GitHub', 'OLD', username='old')
    temp_db.update_account(rid, username='new')   # 不改密码
    rec = temp_db.get_account(rid)
    assert rec['username'] == 'new'
    assert rec['password_enc'] == 'OLD'


def test_delete(temp_db):
    rid = temp_db.add_account('X', 'e')
    temp_db.delete_account(rid)
    assert temp_db.get_account(rid) is None
    assert temp_db.count_accounts() == 0


def test_name_exists(temp_db):
    rid = temp_db.add_account('GitHub', 'e')
    assert temp_db.name_exists('GitHub') is True
    assert temp_db.name_exists('GitHub', exclude_id=rid) is False
    assert temp_db.name_exists('Gmail') is False


# ---------- 加密层（Windows DPAPI）----------
@pytest.mark.skipif(sys.platform != 'win32',
                    reason='DPAPI 仅在 Windows 可用')
def test_encrypt_decrypt_roundtrip():
    plain = 'p@ss 中文 123!'
    token = vault_crypto.encrypt(plain)
    assert token != plain              # 密文不等于明文
    assert plain not in token          # 明文不出现在密文里
    assert vault_crypto.decrypt(token) == plain


@pytest.mark.skipif(sys.platform != 'win32',
                    reason='DPAPI 仅在 Windows 可用')
def test_encrypt_rejects_empty():
    with pytest.raises(ValueError):
        vault_crypto.encrypt('')


@pytest.mark.skipif(sys.platform != 'win32',
                    reason='DPAPI 仅在 Windows 可用')
def test_encrypt_is_nondeterministic():
    """每次加密结果不同（DPAPI 带随机盐），但都能解回同一明文。"""
    a = vault_crypto.encrypt('same')
    b = vault_crypto.encrypt('same')
    assert a != b
    assert vault_crypto.decrypt(a) == vault_crypto.decrypt(b) == 'same'
