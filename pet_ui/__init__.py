"""桌宠 UI 包（由原单文件 pet_ui.py 拆分而来）。

对外保持与拆分前完全相同的导入方式：

    from pet_ui import PetApp

内部分层：
    theme.py       配色与渲染参数常量
    renderer.py    图像流水线（Pillow：抠底 / 阴影 / 帧合成 / 占位图）
    animations.py  呼吸 / 挤压 / 拎起动画
    popup.py       气泡卡片 + MVP 徽章 + 冠军登场特效
    heatmap.py     键盘热力图
    table.py       历史表格
    checkbox.py    自绘圆形勾选框（日程表用）
    schedule.py    日程表（独立窗口 + 头顶角标）
    app.py         PetApp 主类（窗口 / 图标 / 拖拽 / 菜单）

兼容层：拆分前的一些模块级符号（IDLE_FRAMES、_prepare_pet 等）
仍可从本包顶层导入，供旧脚本（如 _frames_preview.py）继续使用。
"""

from pet_ui.app import PetApp

# ---- 兼容导出（拆分前的模块级符号）----
from pet_ui.theme import (          # noqa: F401
    TRANSPARENT,
    TRANSPARENT_RGB,
    PRIMARY,
    PRIMARY_DARK,
    TEXT_DARK,
    TEXT_MUTED,
    IDLE_FRAMES,
    IDLE_INTERVAL,
    SQUASH_INTERVAL,
    PAD_X,
    PAD_TOP,
    SHADOW_H_RATIO,
)
from pet_ui.renderer import (       # noqa: F401
    _has_alpha,
    _prepare_pet,
    _make_shadow,
    _compose_frame,
    frame_to_photo,
    _placeholder_icon,
)

__all__ = ['PetApp']
