"""exe 名 → 友好名 + 分类的映射。

为什么需要它：
- `weixin.exe` 对人不好读，对 AI 也没有语义；
- `{"name": "微信", "category": "chat"}` 人和 AI 都能直接理解，
  AI 读统计 JSON 时不需要先猜这个 exe 是什么。

数据来源：项目根的 `app_aliases.json`（可手动增补，不需要改代码）。
文件缺失或损坏时用下面的内置默认表兜底，保证功能可用。

分类取值固定，不要塞数字编码——`dev` / `chat` 这类词 AI 能直接读懂：

    dev      写代码的编辑器、IDE
    terminal 终端 / shell
    browse   浏览器
    chat     即时通讯
    work     办公协作（文档、邮件、会议）
    media    影音娱乐
    other    未归类（默认兜底）
"""
import json
import os

from config import BASE_DIR
from logger import logger

ALIASES_PATH = os.path.join(BASE_DIR, 'app_aliases.json')

# 固定的分类集合（顺序即界面展示优先级）
CATEGORIES = ('dev', 'terminal', 'browse', 'chat', 'work', 'media', 'other')
CATEGORY_LABELS = {
    'dev': '开发',
    'terminal': '终端',
    'browse': '浏览',
    'chat': '聊天',
    'work': '办公',
    'media': '影音',
    'other': '其他',
}

# 内置默认映射。用户可在 app_aliases.json 里覆盖或补充。
DEFAULT_ALIASES = {
    # 开发
    'code.exe': {'name': 'VS Code', 'category': 'dev'},
    'cursor.exe': {'name': 'Cursor', 'category': 'dev'},
    'trae.exe': {'name': 'Trae', 'category': 'dev'},
    'pycharm64.exe': {'name': 'PyCharm', 'category': 'dev'},
    'idea64.exe': {'name': 'IntelliJ IDEA', 'category': 'dev'},
    'devenv.exe': {'name': 'Visual Studio', 'category': 'dev'},
    'clion64.exe': {'name': 'CLion', 'category': 'dev'},
    'goland64.exe': {'name': 'GoLand', 'category': 'dev'},
    'webstorm64.exe': {'name': 'WebStorm', 'category': 'dev'},
    'sublime_text.exe': {'name': 'Sublime Text', 'category': 'dev'},
    'notepad++.exe': {'name': 'Notepad++', 'category': 'dev'},
    'androidstudio64.exe': {'name': 'Android Studio', 'category': 'dev'},
    'eclipse.exe': {'name': 'Eclipse', 'category': 'dev'},
    'labview.exe': {'name': 'LabVIEW', 'category': 'dev'},
    'keil.exe': {'name': 'Keil', 'category': 'dev'},
    'arduino ide.exe': {'name': 'Arduino IDE', 'category': 'dev'},
    'arduinoide.exe': {'name': 'Arduino IDE', 'category': 'dev'},

    # 终端
    'windowsterminal.exe': {'name': 'Windows 终端', 'category': 'terminal'},
    'wt.exe': {'name': 'Windows 终端', 'category': 'terminal'},
    'cmd.exe': {'name': '命令提示符', 'category': 'terminal'},
    'powershell.exe': {'name': 'PowerShell', 'category': 'terminal'},
    'pwsh.exe': {'name': 'PowerShell', 'category': 'terminal'},
    'conhost.exe': {'name': '控制台', 'category': 'terminal'},
    'mintty.exe': {'name': 'Git Bash', 'category': 'terminal'},
    'bash.exe': {'name': 'Bash', 'category': 'terminal'},

    # 浏览器
    'chrome.exe': {'name': 'Chrome', 'category': 'browse'},
    'msedge.exe': {'name': 'Edge', 'category': 'browse'},
    'firefox.exe': {'name': 'Firefox', 'category': 'browse'},
    'brave.exe': {'name': 'Brave', 'category': 'browse'},
    'opera.exe': {'name': 'Opera', 'category': 'browse'},

    # 聊天 / 社交
    'wechat.exe': {'name': '微信', 'category': 'chat'},
    'weixin.exe': {'name': '微信', 'category': 'chat'},
    'qq.exe': {'name': 'QQ', 'category': 'chat'},
    'dingtalk.exe': {'name': '钉钉', 'category': 'chat'},
    'telegram.exe': {'name': 'Telegram', 'category': 'chat'},
    'discord.exe': {'name': 'Discord', 'category': 'chat'},
    'whatsapp.exe': {'name': 'WhatsApp', 'category': 'chat'},

    # 办公 / 协作
    'feishu.exe': {'name': '飞书', 'category': 'work'},
    'lark.exe': {'name': '飞书', 'category': 'work'},
    'wework.exe': {'name': '企业微信', 'category': 'work'},
    'wps.exe': {'name': 'WPS', 'category': 'work'},
    'winword.exe': {'name': 'Word', 'category': 'work'},
    'excel.exe': {'name': 'Excel', 'category': 'work'},
    'powerpnt.exe': {'name': 'PowerPoint', 'category': 'work'},
    'onenote.exe': {'name': 'OneNote', 'category': 'work'},
    'outlook.exe': {'name': 'Outlook', 'category': 'work'},
    'notion.exe': {'name': 'Notion', 'category': 'work'},
    'obsidian.exe': {'name': 'Obsidian', 'category': 'work'},
    'simplenote.exe': {'name': 'Simplenote', 'category': 'work'},
    'acrobat.exe': {'name': 'Acrobat', 'category': 'work'},
    'acrord32.exe': {'name': 'Acrobat Reader', 'category': 'work'},

    # 影音 / 娱乐
    'potplayermini64.exe': {'name': 'PotPlayer', 'category': 'media'},
    'vlc.exe': {'name': 'VLC', 'category': 'media'},
    'cloudmusic.exe': {'name': '网易云音乐', 'category': 'media'},
    'qqmusic.exe': {'name': 'QQ 音乐', 'category': 'media'},
    'spotify.exe': {'name': 'Spotify', 'category': 'media'},
    'steam.exe': {'name': 'Steam', 'category': 'media'},
    'bilibili.exe': {'name': '哔哩哔哩', 'category': 'media'},
    'jianyingpro.exe': {'name': '剪映', 'category': 'media'},

    # Windows 系统进程：会以「前台窗口」身份捕获到按键，不映射的话
    # 界面上就只剩一串生僻的 exe 名
    'explorer.exe': {'name': '文件资源管理器', 'category': 'work'},
    'lockapp.exe': {'name': '锁屏', 'category': 'other'},
    'searchapp.exe': {'name': '系统搜索', 'category': 'other'},
    'startmenuexperiencehost.exe': {'name': '开始菜单', 'category': 'other'},
    'shellexperiencehost.exe': {'name': '系统界面', 'category': 'other'},
    'applicationframehost.exe': {'name': 'UWP 应用', 'category': 'other'},
    'textinputhost.exe': {'name': '输入法', 'category': 'other'},

    # 特殊归属（非真实 exe）：让总数与明细能对得上
    '__host__': {'name': '桌宠', 'category': 'other'},
    '__unattributed__': {'name': '未识别', 'category': 'other'},
}

# 进程级缓存：避免每敲一次键都读磁盘。
_cache = None


def _normalize(exe):
    """统一 exe 名为小写，作为查表 key。"""
    return (exe or '').strip().lower()


def load_aliases(path=ALIASES_PATH, force=False):
    """读取别名表（默认带缓存）。

    返回 {exe: {'name': str, 'category': str}}。
    文件里的条目会**覆盖**同名的内置默认条目，其余默认项保留。
    """
    global _cache
    if _cache is not None and not force:
        return _cache

    merged = {k: dict(v) for k, v in DEFAULT_ALIASES.items()}
    if path and os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                user_data = json.load(f)
            if isinstance(user_data, dict):
                for exe, info in user_data.items():
                    if not isinstance(info, dict):
                        continue
                    key = _normalize(exe)
                    merged[key] = {
                        'name': str(info.get('name') or exe),
                        'category': str(info.get('category') or 'other'),
                    }
        except Exception:
            logger.exception('app_aliases.json 读取失败，使用内置默认表')
    _cache = merged
    return _cache


def resolve(exe, aliases=None):
    """把 exe 名解析成 {'exe', 'name', 'category'}。

    未命中映射时兜底：name 用原始 exe 名去掉后缀，category 为 'other'。
    这样既不会崩，也能让用户一眼看出「这个软件还没归类」。
    """
    raw = exe or ''
    key = _normalize(raw)
    table = aliases if aliases is not None else load_aliases()
    info = table.get(key)
    if info:
        return {'exe': raw, 'name': info['name'],
                'category': info['category']}
    fallback = os.path.splitext(raw)[0] if raw else '未知'
    return {'exe': raw, 'name': fallback, 'category': 'other'}


def is_known(exe, aliases=None):
    """该 exe 是否在映射表里（用于提示用户补全）。"""
    table = aliases if aliases is not None else load_aliases()
    return _normalize(exe) in table


def write_default_file(path=ALIASES_PATH):
    """把内置默认表写成一个可编辑的 app_aliases.json（初始化用）。

    已存在则不覆盖，避免冲掉用户的自定义项。
    """
    if os.path.exists(path):
        return False
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_ALIASES, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        logger.exception('写入默认 app_aliases.json 失败')
        return False
