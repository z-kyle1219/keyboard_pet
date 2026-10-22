"""天气播报气泡：星夜主题卡片（Pillow 渲染 + 知道了 / 查看详情）。

设计（与 popup.py 同套路，离屏渲染成一张图，tkinter 只负责显示）：
- 深蓝夜空底 + 月牙 + 星点（纯色叠画，不用渐变，避免渲染差异）
- 两个校区各一块半透明玻璃卡片
- 底部两个按钮：知道了（描边）/ 查看详情（暖金实心）

线程安全：本模块所有方法都必须由主线程调用。
天气线程只能通过 root.after(0, ...) 调度到主线程后再调 show_weather()。
"""
import tkinter as tk
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageTk

from logger import logger

# ---------- 星夜配色 ----------
SKY_TOP = (19, 42, 92)       # 上半天际（略亮）
SKY_BOTTOM = (14, 31, 69)    # 主夜色
MOON = (255, 246, 208)
MOON_GLOW = (255, 251, 232)
STAR = (255, 255, 255)
GLASS = (255, 255, 255)
GLASS_BORDER = (143, 176, 224)
TEXT_TITLE = (234, 240, 255)
TEXT_NAME = (169, 196, 236)
TEXT_BODY = (234, 240, 255)
TEXT_TEMP = (255, 240, 184)   # 暖金
BTN_GHOST_TEXT = (234, 240, 255)
BTN_GOLD = (255, 217, 138)
BTN_GOLD_TEXT = (61, 42, 0)

CARD_W = 320
CARD_H = 440
RADIUS = 18

# 字体（Windows 中文）；取不到时退回默认
_FONT_PATHS = [
    r'C:\Windows\Fonts\msyh.ttc',    # 微软雅黑
    r'C:\Windows\Fonts\msyhbd.ttc',
    r'C:\Windows\Fonts\simhei.ttf',
]


def _load_font(size, bold=False):
    """加载中文字体，失败退回 Pillow 默认字体。"""
    path = _FONT_PATHS[1 if bold else 0]
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.truetype(_FONT_PATHS[2], size)
        except Exception:
            return ImageFont.load_default()


def _render_card(current, changes):
    """把天气数据渲染成一张星夜卡片（Pillow）。

    current: {地点名: {"text","temp","wind_scale","wind_dir"}}
    changes: 突变描述列表（非空时在底部加一行提醒）
    返回: (PIL.Image, 按钮命中区域 dict)
    """
    img = Image.new('RGB', (CARD_W, CARD_H), SKY_BOTTOM)
    d = ImageDraw.Draw(img, 'RGBA')

    # 上半天际略亮（模拟夜空层次，用矩形分块代替渐变）
    d.rectangle([0, 0, CARD_W, 150], fill=SKY_TOP + (150,))

    # 月牙 + 光晕
    d.ellipse([252 - 46, 70 - 46, 252 + 46, 70 + 46], fill=MOON_GLOW + (26,))
    d.ellipse([252 - 24, 70 - 24, 252 + 24, 70 + 24], fill=MOON)
    d.ellipse([252 + 12 - 20, 70 - 8 - 20, 252 + 12 + 20, 70 - 8 + 20],
              fill=SKY_TOP + (255,))

    # 星点
    stars = [(50, 52, 2), (88, 96, 1), (40, 128, 1), (132, 44, 1),
             (176, 86, 1), (112, 140, 1), (212, 128, 1), (290, 150, 1),
             (64, 180, 1)]
    for x, y, r in stars:
        d.ellipse([x - r, y - r, x + r, y + r], fill=STAR + (200,))

    # 标题
    f_title = _load_font(16, bold=True)
    title = '今 夜 天 气'
    tw = d.textlength(title, font=f_title)
    d.text(((CARD_W - tw) / 2, 30), title, font=f_title, fill=TEXT_TITLE)
    d.line([108, 58, 212, 58], fill=GLASS_BORDER + (90,), width=1)

    # 两个校区的玻璃卡片
    f_name = _load_font(12)
    f_body = _load_font(12)
    f_temp = _load_font(20, bold=True)

    top = 86
    for name, w in current.items():
        d.rounded_rectangle([20, top, CARD_W - 20, top + 104], radius=14,
                            fill=GLASS + (20,),
                            outline=GLASS_BORDER + (77,), width=1)
        d.text((38, top + 16), name, font=f_name, fill=TEXT_NAME)
        body = f"{w.get('text', '')}　·　风速 {w.get('wind_scale', '')} 级"
        d.text((38, top + 41), body, font=f_body, fill=TEXT_BODY)
        d.text((38, top + 68), f"{w.get('temp', '')}°", font=f_temp,
               fill=TEXT_TEMP)
        top += 114

    # 突变提醒（若有）
    if changes:
        f_warn = _load_font(11)
        d.text((20, top - 6), '⚠ ' + '；'.join(changes), font=f_warn,
               fill=(255, 180, 120))

    # 按钮
    btn_y = 326
    btn_h = 44
    d.rounded_rectangle([20, btn_y, 152, btn_y + btn_h], radius=22,
                        fill=GLASS + (31,), outline=GLASS_BORDER + (115,),
                        width=1)
    d.rounded_rectangle([168, btn_y, 300, btn_y + btn_h], radius=22,
                        fill=BTN_GOLD)
    f_btn = _load_font(13)
    for text, cx in (('知道了', 86), ('查看详情', 234)):
        color = BTN_GHOST_TEXT if text == '知道了' else BTN_GOLD_TEXT
        tw = d.textlength(text, font=f_btn)
        d.text((cx - tw / 2, btn_y + 13), text, font=f_btn, fill=color)

    # 底部小字
    f_tip = _load_font(10)
    tip = '点「知道了」今夜不再打扰 · 天气突变仍会提醒'
    tw = d.textlength(tip, font=f_tip)
    d.text(((CARD_W - tw) / 2, 400), tip, font=f_tip,
           fill=TEXT_NAME + (217,))

    hits = {
        'confirm': (20, btn_y, 152, btn_y + btn_h),
        'detail': (168, btn_y, 300, btn_y + btn_h),
    }
    return img, hits


class WeatherMixin:
    """天气气泡：作为 Mixin 混入 PetApp。"""

    def show_weather(self, current, changes=None):
        """显示天气卡片（必须在主线程调用）。

        天气线程通过 root.after(0, lambda: self.show_weather(...)) 调度过来。
        """
        if not current:
            return
        # 关闭上一个天气卡片
        if getattr(self, '_weather_win', None) is not None:
            try:
                self._weather_win.destroy()
            except Exception:
                pass
            self._weather_win = None

        try:
            card, hits = _render_card(current, changes or [])
            photo = ImageTk.PhotoImage(card)
        except Exception:
            logger.exception('天气卡片渲染失败')
            return

        win = tk.Toplevel(self.root)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.config(bg='#0E1F45')

        x = self.root.winfo_x() + self._frame_w // 2 - CARD_W // 2
        y = self.root.winfo_y() - CARD_H - 8
        if y < 0:
            y = self.root.winfo_y() + self._frame_h + 8
        win.geometry(f'{CARD_W}x{CARD_H}+{x}+{y}')

        canvas = tk.Canvas(win, width=CARD_W, height=CARD_H,
                           highlightthickness=0, bd=0, bg='#0E1F45')
        canvas.pack()
        canvas.create_image(0, 0, image=photo, anchor='nw')
        canvas._card_img = photo   # 防 GC

        def _hit_confirm(e):
            self._on_weather_confirm()

        def _hit_detail(e):
            self._on_weather_detail(current, changes or [])

        for key, (x1, y1, x2, y2) in hits.items():
            tag = f'btn_{key}'
            canvas.create_rectangle(x1, y1, x2, y2, fill='', outline='',
                                    tags=tag)
            cb = _hit_confirm if key == 'confirm' else _hit_detail
            canvas.tag_bind(tag, '<Button-1>', cb)

        self._weather_win = win
        win.deiconify()

    def _on_weather_confirm(self):
        """点「知道了」：记录当天已确认，然后关闭卡片。"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            state = getattr(self, '_weather_state', None)
            if state is not None:
                state.confirm(today)
        except Exception:
            logger.exception('确认天气失败')
        self._close_weather()

    def _on_weather_detail(self, current, changes):
        """点「查看详情」：暂时复用桌宠气泡显示完整文字。"""
        try:
            lines = [f"{name}：{w.get('text', '')}，"
                     f"风速 {w.get('wind_scale', '')} 级，"
                     f"气温 {w.get('temp', '')}℃"
                     for name, w in current.items()]
            if changes:
                lines.append('⚠ ' + '；'.join(changes))
            self._toast('\n'.join(lines))
        except Exception:
            logger.exception('查看详情失败')

    def _close_weather(self):
        """关闭天气卡片。"""
        w = getattr(self, '_weather_win', None)
        if w is not None:
            try:
                w.destroy()
            except Exception:
                pass
        self._weather_win = None
