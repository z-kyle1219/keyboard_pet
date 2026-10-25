"""密码本加密层：用 Windows DPAPI 对密码做落库前的加密。

安全红线（见 AGENTS.md「红线」）：
- **绝不**把密码明文写进数据库：库里只存 DPAPI 加密后的密文（base64）。
- **不自造加密算法**：直接调用操作系统提供的 CryptProtectData /
  CryptUnprotectData；加密密钥由 Windows 绑定到「当前登录用户」，本模块
  不管理、不落盘任何密钥。
- 解密后的明文只在内存里短暂存在：调用方（db_vault / UI）用完即弃，
  **不写日志、不进异常消息**。

DPAPI 的安全语义（等同系统钥匙串）：
- 密文只能被**同一台机器上的同一个 Windows 账户**解开：把
  keyboard_stats.db 拷到别的机器 / 别的账户无法解密。
- 但以该用户身份运行的程序都能解密——本工具是本地单机用途，
  仍应保证机器本身不被他人随意使用。
- 附加熵 _ENTROPY 进一步把密文限定给本程序，降低被其它程序
  误用同一账户密钥解密的机会。

平台：仅 Windows（本项目即 Windows 桌宠）。非 Windows 下调用会抛
RuntimeError，便于上层给出清晰提示而不是静默失败。
"""
import base64
import ctypes
import sys

# 附加熵：把密文限定为「本程序 + 本版本」所产生
_ENTROPY = b'keyboard_pet.vault.v1'

# CryptProtectData 标志：禁止弹 UI（后台线程安全，不阻塞）
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    """ctypes 版的 DATA_BLOB（CryptProtectData 的输入/输出结构）。"""

    _fields_ = [
        ('cbData', ctypes.c_ulong),
        ('pbData', ctypes.POINTER(ctypes.c_char)),
    ]


def _make_blob(data):
    """把 bytes 包装成 DATA_BLOB，并返回 (blob, buf) 。

    必须同时返回 buf（ctypes buffer）并让调用方持有它，否则会被 GC 回收，
    导致 DATA_BLOB.pbData 变成悬垂指针。
    """
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    return blob, buf


def _crypt32():
    """取 crypt32 / kernel32 的函数入口，并声明参数类型。

    DPAPI 输出指针在 64 位下是 8 字节，不声明 restype/argtypes 时
    ctypes 默认按 int(32 位) 截断，会拿到非法指针。故显式声明。
    """
    if sys.platform != 'win32':
        raise RuntimeError('密码本加密依赖 Windows DPAPI，当前系统不受支持')
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.restype = ctypes.c_int
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    return crypt32, kernel32


def is_available():
    """当前环境是否支持加密（仅 Windows）。供上层做能力探测/提示。"""
    return sys.platform == 'win32'


def _protect(raw):
    """用 DPAPI 加密原始字节，返回密文字节。"""
    crypt32, kernel32 = _crypt32()
    in_blob, _in_buf = _make_blob(raw)
    ent_blob, _ent_buf = _make_blob(_ENTROPY)
    out_blob = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, ctypes.byref(ent_blob),
        None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError('DPAPI 加密失败（CryptProtectData 返回 0）')
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        # 输出缓冲区由系统分配，必须 LocalFree 归还
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _unprotect(raw):
    """用 DPAPI 解密原始密文字节，返回明文字节。"""
    crypt32, kernel32 = _crypt32()
    in_blob, _in_buf = _make_blob(raw)
    ent_blob, _ent_buf = _make_blob(_ENTROPY)
    out_blob = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, ctypes.byref(ent_blob),
        None, None, _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError('DPAPI 解密失败：密文损坏，或换了机器/账户')
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def encrypt(plaintext):
    """明文 → 可落库的密文字符串（base64）。

    空字符串会被拒绝：密码本里不该存空密码（多半是误操作）。
    """
    if plaintext is None or plaintext == '':
        raise ValueError('密码不能为空')
    return base64.b64encode(_protect(plaintext.encode('utf-8'))).decode('ascii')


def decrypt(token):
    """密文字符串（base64）→ 明文。密文非法 / 跨机器时抛 OSError。"""
    if not token:
        raise ValueError('密文为空')
    raw = base64.b64decode(token.encode('ascii'), validate=True)
    return _unprotect(raw).decode('utf-8')
