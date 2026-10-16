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

# 桌宠显示高度（像素）。人物图标宽度按宽高比自适应；
# 无透明通道的图标按正方形圆角兜底处理。
PET_HEIGHT = 160

# 支持的图片后缀
_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp'}


def find_icon():
    """自动在 assets/ 里找一张可用图片作为桌宠图标。

    优先选择带透明通道的 PNG（人物轮廓最适合做桌宠）；
    找不到透明图时回退到任意第一张图片。找不到任何图片返回 None。
    好处：用户直接替换 assets/ 里的图片即可生效，无需改代码、无需改配置。
    """
    if not os.path.isdir(ASSETS_DIR):
        return None
    names = sorted(os.listdir(ASSETS_DIR))
    # 第一轮：优先带透明通道的 PNG
    for name in names:
        if os.path.splitext(name)[1].lower() != '.png':
            continue
        path = os.path.join(ASSETS_DIR, name)
        try:
            from PIL import Image
            with Image.open(path) as im:
                if im.mode in ('RGBA', 'LA') or \
                        (im.mode == 'P' and 'transparency' in im.info):
                    return path
        except Exception:
            continue
    # 第二轮：回退到任意第一张图片
    for name in names:
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
