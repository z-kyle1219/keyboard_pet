"""图像渲染流水线：图标预处理、阴影、帧合成、tkinter 显示转换。

从原 pet_ui.py 原样迁移的纯函数集合（无状态、不依赖 PetApp 实例），
供桌宠外观绘制与动画帧预生成使用。
"""
import math

from PIL import Image, ImageDraw, ImageTk, ImageFilter

import config
from pet_ui.theme import (
    TRANSPARENT_RGB,
    PAD_X,
    PAD_TOP,
    SHADOW_H_RATIO,
)


def _has_alpha(img):
    """判断图片是否带透明通道。"""
    if img.mode in ('RGBA', 'LA'):
        return True
    if img.mode == 'P' and 'transparency' in img.info:
        return True
    return False


def _prepare_pet(img, pet_h):
    """把原始图标转成基准人物 RGBA（高度=pet_h）。

    透明图：等比缩放保留人物轮廓；无透明图：居中裁正方形 + 圆角兜底。
    """
    if _has_alpha(img):
        w, h = img.size
        pet_w = max(1, round(pet_h * w / h))
        return img.convert('RGBA').resize((pet_w, pet_h), Image.LANCZOS)
    # 无透明通道：沿用旧的圆角处理，避免生硬矩形
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side)).convert('RGBA')
    img = img.resize((pet_h, pet_h), Image.LANCZOS)
    radius = max(8, int(pet_h * 0.28))
    mask = Image.new('L', (pet_h, pet_h), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, pet_h, pet_h], radius=radius, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(pet_h * 0.03))
    out = Image.new('RGBA', (pet_h, pet_h), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _make_shadow(pet_w, shadow_h, scale=1.0):
    """生成柔和椭圆阴影（不透明灰色渐变，模拟 alpha 阴影）。

    tkinter 的 transparentcolor 只抠纯色、不支持半透明，故阴影用多层同心
    椭圆从内到外渐浅的灰色来模拟柔边，浅色桌面下边界自然。
    """
    sw = max(1, round(pet_w * scale))
    sh = max(1, round(shadow_h * scale))
    img = Image.new('RGBA', (sw, sh), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    layers = [
        (0.40, (176, 176, 184, 255)),
        (0.34, (188, 188, 196, 255)),
        (0.28, (200, 200, 207, 255)),
        (0.22, (212, 212, 218, 255)),
        (0.16, (224, 224, 229, 255)),
    ]
    for r, col in layers:
        d.ellipse([sw * (0.5 - r / 2), sh * 0.15,
                   sw * (0.5 + r / 2), sh * 0.95], fill=col)
    return img


def _compose_frame(pet, shadow_scale, lift, squash=(1.0, 1.0)):
    """合成一帧完整渲染图（RGBA）：人物 + 底部阴影。

    pet          基准人物 RGBA
    shadow_scale 阴影缩放系数（呼吸/拎起时变化）
    lift         人物上浮像素
    squash       (sx, sy) 挤压因子，用于点击回弹
    """
    pw, ph = pet.size
    sx, sy = squash
    nw = max(1, round(pw * sx))
    nh = max(1, round(ph * sy))
    p = pet.resize((nw, nh), Image.LANCZOS)

    shadow_h = round(ph * SHADOW_H_RATIO)
    shadow = _make_shadow(pw, shadow_h, shadow_scale)

    W = pw + 2 * PAD_X
    H = ph + PAD_TOP + shadow_h + 6

    frame = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    sw, sh = shadow.size
    frame.alpha_composite(shadow, ((W - sw) // 2, H - sh - 2))
    px = (W - nw) // 2
    py = PAD_TOP + (ph - nh) // 2 - lift
    frame.alpha_composite(p, (px, py))
    return frame


def frame_to_photo(frame):
    """把 RGBA 帧转成品红抠底的 PhotoImage（tkinter 可显示）。

    二值化 alpha：>=128 保留前景色，<128 填品红，由窗口 transparentcolor 抠掉。
    """
    w, h = frame.size
    base = Image.new('RGB', (w, h), TRANSPARENT_RGB)
    fg = frame.convert('RGB')
    mask = frame.getchannel('A').point(lambda a: 255 if a >= 128 else 0)
    base.paste(fg, (0, 0), mask)
    return ImageTk.PhotoImage(base)


def _placeholder_icon():
    """生成一个简单的占位水母图标（RGBA），用于图片加载失败时兜底。"""
    size = config.PET_HEIGHT
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 120.0
    # 身体
    d.ellipse([18 * s, 12 * s, 102 * s, 78 * s], fill=(255, 170, 190, 210))
    d.ellipse([36 * s, 26 * s, 86 * s, 66 * s], fill=(255, 214, 224, 160))
    # 触须
    for t in range(5):
        base_x = (30 + t * 14) * s
        pts = []
        for step in range(0, 40):
            y = (72 + step * 1.1) * s
            x = base_x + math.sin(step / 4.0 + t) * 6 * s
            pts.append((x, y))
        d.line(pts, fill=(255, 170, 190, 180), width=max(1, int(2 * s)))
    return img
