"""配置模块：集中管理路径与用户自定义项。

职责：
- 定义项目目录、数据库、配置、资源目录路径
- 使用用户手动上传到 assets/ 的图标
"""
import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, 'assets')
DB_PATH = os.path.join(BASE_DIR, 'keyboard_stats.db')
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')

# 桌宠显示尺寸（正方形，像素）
PET_SIZE = 120

# 支持的图片后缀
_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp'}


def find_icon():
    """自动在 assets/ 里找第一张可用图片作为桌宠图标。

    好处：用户直接替换 assets/ 里的图片即可生效，无需改代码、无需改配置。
    找不到任何图片时返回 None，由界面回退到内置占位图。
    """
    if not os.path.isdir(ASSETS_DIR):
        return None
    for name in sorted(os.listdir(ASSETS_DIR)):
        if os.path.splitext(name)[1].lower() in _IMAGE_EXTS:
            return os.path.join(ASSETS_DIR, name)
    return None


# 默认图标：assets/ 里自动发现的第一张图片
PET_ICON = find_icon()

_DEFAULTS = {
    # 默认使用 assets/ 里自动发现的第一张图片
    'icon_path': PET_ICON,
}


def load_config():
    """读取配置，缺失字段用默认值补齐。"""
    cfg = dict(_DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    return cfg


def save_config(cfg):
    """保存配置到 config.json。"""
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
